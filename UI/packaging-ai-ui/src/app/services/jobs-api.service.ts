import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { environment } from '../../environments/environment';
import {
  ArtifactsResponse,
  ClarifyRequest,
  CreateJobRequest,
  CreateJobResponse,
  JobResponse,
  LogContentResponse,
  LogListResponse,
} from '../models/job';

/**
 * Browser never holds the API key. IIS (prod) or the Angular proxy (dev)
 * injects X-API-Key when forwarding /v1 to uvicorn.
 */
@Injectable({ providedIn: 'root' })
export class JobsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl.replace(/\/$/, '');

  createJob(body: CreateJobRequest): Observable<CreateJobResponse> {
    return this.http
      .post<CreateJobResponse>(`${this.base}/v1/jobs`, body, {
        headers: this.jsonHeaders(),
      })
      .pipe(catchError((err) => this.mapError(err)));
  }

  getJob(jobId: string): Observable<JobResponse> {
    return this.http
      .get<JobResponse>(`${this.base}/v1/jobs/${jobId}`, {
        headers: this.jsonHeaders(),
      })
      .pipe(catchError((err) => this.mapError(err)));
  }

  clarify(jobId: string, body: ClarifyRequest): Observable<JobResponse> {
    return this.http
      .post<JobResponse>(`${this.base}/v1/jobs/${jobId}/clarify`, body, {
        headers: this.jsonHeaders(),
      })
      .pipe(catchError((err) => this.mapError(err)));
  }

  cancel(jobId: string): Observable<JobResponse> {
    return this.http
      .post<JobResponse>(
        `${this.base}/v1/jobs/${jobId}/cancel`,
        {},
        { headers: this.jsonHeaders() },
      )
      .pipe(catchError((err) => this.mapError(err)));
  }

  getArtifacts(jobId: string): Observable<ArtifactsResponse> {
    return this.http
      .get<ArtifactsResponse>(`${this.base}/v1/jobs/${jobId}/artifacts`, {
        headers: this.jsonHeaders(),
      })
      .pipe(catchError((err) => this.mapError(err)));
  }

  listLogs(jobId: string): Observable<LogListResponse> {
    return this.http
      .get<LogListResponse>(`${this.base}/v1/jobs/${jobId}/logs`, {
        headers: this.jsonHeaders(),
      })
      .pipe(catchError((err) => this.mapError(err)));
  }

  getLogContent(jobId: string, fileName: string): Observable<LogContentResponse> {
    const encoded = encodeURIComponent(fileName);
    return this.http
      .get<LogContentResponse>(`${this.base}/v1/jobs/${jobId}/logs/${encoded}`, {
        headers: this.jsonHeaders(),
      })
      .pipe(catchError((err) => this.mapError(err)));
  }

  private jsonHeaders(): HttpHeaders {
    return new HttpHeaders({ 'Content-Type': 'application/json' });
  }

  private mapError(err: unknown): Observable<never> {
    if (err instanceof HttpErrorResponse) {
      const detail = this.extractDetail(err);
      return throwError(() => new Error(detail || `HTTP ${err.status}`));
    }
    return throwError(() => err);
  }

  private extractDetail(err: HttpErrorResponse): string {
    const body = err.error;
    if (typeof body === 'string' && body.trim()) {
      return body;
    }
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === 'string') {
        return detail;
      }
      if (Array.isArray(detail)) {
        return detail
          .map((item) =>
            typeof item === 'object' && item && 'msg' in item
              ? String((item as { msg: unknown }).msg)
              : JSON.stringify(item),
          )
          .join('; ');
      }
      return JSON.stringify(detail);
    }
    if (err.status === 401) {
      return 'API rejected the request (missing/invalid API key). Check IIS or the Angular proxy injects X-API-Key.';
    }
    if (err.status === 0) {
      return 'Cannot reach the API. Is it running, and is the proxy configured?';
    }
    return err.message || `Request failed (${err.status})`;
  }
}
