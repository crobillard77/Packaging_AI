import { DecimalPipe } from '@angular/common';
import { Component, OnDestroy, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subscription, switchMap, takeWhile, timer } from 'rxjs';

import { environment } from '../environments/environment';
import {
  ArtifactsResponse,
  ClarificationNeeded,
  JobResponse,
  JobStatus,
  LogContentResponse,
  LogFileInfo,
} from './models/job';
import { JobsApiService } from './services/jobs-api.service';

type WizardStep = 'sources' | 'progress' | 'clarify' | 'complete' | 'error';

@Component({
  selector: 'app-root',
  imports: [FormsModule, DecimalPipe],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnDestroy {
  private readonly api = inject(JobsApiService);
  private pollSub: Subscription | null = null;

  readonly pollSeconds = environment.pollIntervalMs / 1000;
  readonly step = signal<WizardStep>('sources');
  readonly busy = signal(false);
  readonly errorMessage = signal('');
  readonly job = signal<JobResponse | null>(null);
  readonly artifacts = signal<ArtifactsResponse | null>(null);
  readonly logFiles = signal<LogFileInfo[]>([]);
  readonly selectedLog = signal<LogContentResponse | null>(null);
  readonly logsBusy = signal(false);
  readonly logsError = signal('');

  folderPath = '';
  outputDir = environment.defaultOutputDir;
  autoConfirm = false;
  customRequirements = '';

  meta = '';
  uninstallPaste = '';
  softConfirm = false;
  /** One answer slot per open_question when clarifying custom requirements. */
  customAnswerFields: string[] = [];

  readonly wizardSteps = [
    { id: 'sources' as const, label: 'Sources' },
    { id: 'progress' as const, label: 'Running' },
    { id: 'clarify' as const, label: 'Clarify' },
    { id: 'complete' as const, label: 'Ready' },
  ];

  ngOnDestroy(): void {
    this.stopPolling();
  }

  stepHeading(): string {
    switch (this.step()) {
      case 'sources':
        return 'Create a package';
      case 'progress':
        return 'Packaging in progress';
      case 'clarify':
        return this.isSoftConfirmOnly() ? 'Confirm to continue' : 'Clarification needed';
      case 'complete':
        return 'Package ready';
      case 'error':
        return 'Job ended';
    }
  }

  stepLede(): string {
    switch (this.step()) {
      case 'sources':
        return 'Point at installer sources on the API host. Paths are server-side; the API key is injected by IIS or the local proxy.';
      case 'progress':
        return 'Scan, plan, review, and generate are running. You can cancel while the job is queued or running.';
      case 'clarify':
        if (this.isSoftConfirmOnly()) {
          return 'Review confidence is below the threshold. Confirm to generate the package, or abort.';
        }
        return 'The job paused for missing metadata, uninstall details, or custom-requirement answers.';
      case 'complete':
        return 'Copy the package path below, or open a log if you need to inspect what ran.';
      case 'error':
        return 'The job did not finish successfully. Start another package when you are ready.';
    }
  }

  isSoftConfirmOnly(): boolean {
    const c = this.clarification();
    if (!c?.needs_soft_confirm) {
      return false;
    }
    return (
      !c.needs_meta &&
      !c.needs_uninstall &&
      !c.needs_custom_clarify &&
      this.visibleOpenQuestions(c).length === 0
    );
  }

  isStepDone(id: (typeof this.wizardSteps)[number]['id']): boolean {
    const current = this.step();
    if (current === 'error' || current === 'sources') {
      return false;
    }
    if (current === 'progress') {
      return id === 'sources';
    }
    if (current === 'clarify') {
      return id === 'sources' || id === 'progress';
    }
    // complete
    return id !== 'complete';
  }

  createJob(): void {
    this.errorMessage.set('');
    const folder = this.folderPath.trim();
    if (!folder) {
      this.errorMessage.set('Input folder path is required.');
      return;
    }

    this.busy.set(true);
    const body = {
      folder_path: folder,
      output_dir: this.outputDir.trim() || null,
      auto_confirm: this.autoConfirm,
      custom_requirements: this.customRequirements.trim() || null,
    };

    this.api.createJob(body).subscribe({
      next: (created) => {
        this.busy.set(false);
        this.job.set({
          id: created.id,
          status: created.status,
          folder_path: folder,
          output_dir: body.output_dir,
          auto_confirm: this.autoConfirm,
          confidence_score: null,
          review_findings: [],
          clarification_needed: null,
          plan_summary: null,
          error: null,
          created_at: created.created_at,
          updated_at: created.created_at,
          started_at: null,
          finished_at: null,
        });
        this.step.set('progress');
        this.startPolling(created.id);
      },
      error: (err: Error) => {
        this.busy.set(false);
        this.errorMessage.set(err.message);
      },
    });
  }

  submitClarify(): void {
    const current = this.job();
    const needed = current?.clarification_needed;
    if (!current || !needed) {
      return;
    }

    this.errorMessage.set('');
    if (needed.needs_meta && !this.meta.trim()) {
      this.errorMessage.set('Metadata (Publisher|AppName|Version) is required.');
      return;
    }
    if (needed.needs_uninstall && !this.uninstallPaste.trim()) {
      this.errorMessage.set('Uninstall command is required.');
      return;
    }
    if (needed.needs_soft_confirm && !this.softConfirm) {
      this.errorMessage.set('Please confirm to continue, or abort the job.');
      return;
    }
    if (needed.needs_custom_clarify) {
      const questions = this.visibleOpenQuestions(needed);
      if (questions.length !== this.customAnswerFields.length) {
        this.customAnswerFields = questions.map((_, i) => this.customAnswerFields[i] ?? '');
      }
      const missing = this.customAnswerFields.findIndex((a) => !a.trim());
      if (missing >= 0) {
        this.errorMessage.set(
          `Please answer question ${missing + 1} before submitting.`,
        );
        return;
      }
    }

    this.busy.set(true);
    this.api
      .clarify(current.id, {
        action: 'submit',
        meta: needed.needs_meta ? this.meta.trim() : null,
        uninstall_paste: needed.needs_uninstall ? this.uninstallPaste.trim() : null,
        confirm: needed.needs_soft_confirm ? this.softConfirm : false,
        custom_answers: needed.needs_custom_clarify
          ? this.formatCustomAnswers(this.visibleOpenQuestions(needed))
          : null,
        abort: false,
      })
      .subscribe({
        next: (job) => {
          this.busy.set(false);
          this.applyJob(job);
          if (job.status === 'awaiting_clarification') {
            this.enterClarify(job);
          } else if (this.isTerminal(job.status)) {
            this.handleTerminal(job);
          } else {
            this.step.set('progress');
            this.startPolling(job.id);
          }
        },
        error: (err: Error) => {
          this.busy.set(false);
          this.errorMessage.set(err.message);
        },
      });
  }

  abortClarify(): void {
    const current = this.job();
    if (!current) {
      return;
    }
    this.busy.set(true);
    this.errorMessage.set('');
    this.api.clarify(current.id, { action: 'abort', abort: true }).subscribe({
      next: (job) => {
        this.busy.set(false);
        this.handleTerminal(job);
      },
      error: (err: Error) => {
        this.busy.set(false);
        this.errorMessage.set(err.message);
      },
    });
  }

  cancelJob(): void {
    const current = this.job();
    if (!current) {
      return;
    }
    this.busy.set(true);
    this.errorMessage.set('');
    this.api.cancel(current.id).subscribe({
      next: (job) => {
        this.busy.set(false);
        this.stopPolling();
        this.handleTerminal(job);
      },
      error: (err: Error) => {
        this.busy.set(false);
        this.errorMessage.set(err.message);
      },
    });
  }

  resetWizard(): void {
    this.stopPolling();
    this.step.set('sources');
    this.busy.set(false);
    this.errorMessage.set('');
    this.job.set(null);
    this.artifacts.set(null);
    this.logFiles.set([]);
    this.selectedLog.set(null);
    this.logsBusy.set(false);
    this.logsError.set('');
    this.folderPath = '';
    this.outputDir = environment.defaultOutputDir;
    this.autoConfirm = false;
    this.customRequirements = '';
    this.meta = '';
    this.uninstallPaste = '';
    this.softConfirm = false;
    this.customAnswerFields = [];
  }

  canCancel(status: JobStatus | undefined): boolean {
    return status === 'queued' || status === 'running';
  }

  clarification(): ClarificationNeeded | null {
    return this.job()?.clarification_needed ?? null;
  }

  /** Hide open questions that duplicate the META Publisher|AppName|Version field. */
  visibleOpenQuestions(c: ClarificationNeeded): string[] {
    const questions = c.open_questions ?? [];
    if (!c.needs_meta) {
      return questions;
    }
    return questions.filter((q) => !this.isMetaDuplicateQuestion(q));
  }

  private isMetaDuplicateQuestion(question: string): boolean {
    const q = question.toLowerCase();
    return (
      q.includes('publisher|appname|version') ||
      q.includes('application name is missing') ||
      q.includes('application version is missing') ||
      (q.includes('publisher') && q.includes('appname') && q.includes('version'))
    );
  }

  artifactEntries(): { label: string; path: string }[] {
    const a = this.artifacts();
    if (!a) {
      return [];
    }
    const pairs: [string, string | null][] = [
      ['Deploy script', a.deploy_script],
      ['Logs', a.logs_dir],
      ['Install plan', a.install_plan_path],
      ['Review report', a.review_path],
      ['Requirements', a.requirements_path],
      ['Vulnerability report', a.vulnerability_path],
      ['Packaging log', a.packaging_log_path],
      ['Footprint MST', a.footprint_mst_path],
    ];
    return pairs
      .filter(([, path]) => !!path)
      .map(([label, path]) => ({ label, path: path as string }));
  }

  private startPolling(jobId: string): void {
    this.stopPolling();
    this.pollSub = timer(0, environment.pollIntervalMs)
      .pipe(
        switchMap(() => this.api.getJob(jobId)),
        takeWhile(
          (job) => !this.isTerminal(job.status) && job.status !== 'awaiting_clarification',
          true,
        ),
      )
      .subscribe({
        next: (job) => this.applyJob(job),
        error: (err: Error) => {
          this.stopPolling();
          this.errorMessage.set(err.message);
          this.step.set('error');
        },
      });
  }

  private applyJob(job: JobResponse): void {
    this.job.set(job);
    if (job.status === 'awaiting_clarification') {
      this.stopPolling();
      this.enterClarify(job);
      return;
    }
    if (this.isTerminal(job.status)) {
      this.stopPolling();
      this.handleTerminal(job);
    }
  }

  private enterClarify(job: JobResponse): void {
    const needed = job.clarification_needed;
    this.meta = '';
    this.uninstallPaste = needed?.suggested_uninstall ?? '';
    this.softConfirm = false;
    const questions = needed
      ? this.visibleOpenQuestions(needed)
      : [];
    this.customAnswerFields = questions.map(() => '');
    this.step.set('clarify');
  }

  private formatCustomAnswers(questions: string[]): string {
    return questions
      .map((q, i) => {
        const answer = (this.customAnswerFields[i] ?? '').trim();
        return `Q: ${q}\nA: ${answer}`;
      })
      .join('\n\n');
  }

  formatSize(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  viewLog(fileName: string): void {
    const current = this.job();
    if (!current) {
      return;
    }
    this.logsBusy.set(true);
    this.logsError.set('');
    this.api.getLogContent(current.id, fileName).subscribe({
      next: (content) => {
        this.logsBusy.set(false);
        this.selectedLog.set(content);
      },
      error: (err: Error) => {
        this.logsBusy.set(false);
        this.logsError.set(err.message);
        this.selectedLog.set(null);
      },
    });
  }

  closeLog(): void {
    this.selectedLog.set(null);
  }

  private loadLogs(jobId: string): void {
    this.logsBusy.set(true);
    this.logsError.set('');
    this.logFiles.set([]);
    this.selectedLog.set(null);
    this.api.listLogs(jobId).subscribe({
      next: (list) => {
        this.logsBusy.set(false);
        this.logFiles.set(list.files);
      },
      error: (err: Error) => {
        this.logsBusy.set(false);
        this.logsError.set(err.message);
      },
    });
  }

  private handleTerminal(job: JobResponse): void {
    this.job.set(job);
    if (job.status === 'succeeded') {
      this.step.set('complete');
      this.busy.set(true);
      this.api.getArtifacts(job.id).subscribe({
        next: (artifacts) => {
          this.busy.set(false);
          this.artifacts.set(artifacts);
          this.loadLogs(job.id);
        },
        error: (err: Error) => {
          this.busy.set(false);
          this.errorMessage.set(err.message);
          this.artifacts.set(null);
        },
      });
      return;
    }
    this.step.set('error');
    this.errorMessage.set(job.error || `Job ${job.status}.`);
  }

  private isTerminal(status: JobStatus): boolean {
    return status === 'succeeded' || status === 'failed' || status === 'cancelled';
  }

  private stopPolling(): void {
    this.pollSub?.unsubscribe();
    this.pollSub = null;
  }
}
