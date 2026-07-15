/**
 * Dev proxy: injects X-API-Key so the browser never stores it.
 * Override with env PACKAGING_AI_API_KEYS (same value as the API service).
 */
const apiKey = process.env['PACKAGING_AI_API_KEYS'] || 'dev-key-change-me';

module.exports = {
  '/v1': {
    target: 'http://127.0.0.1:8000',
    secure: false,
    changeOrigin: true,
    headers: {
      'X-API-Key': apiKey,
    },
  },
  '/health': {
    target: 'http://127.0.0.1:8000',
    secure: false,
    changeOrigin: true,
  },
};
