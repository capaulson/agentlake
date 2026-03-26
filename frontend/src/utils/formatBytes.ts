const UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'] as const;

/**
 * Format a byte count to a human-readable string (e.g., "1.5 MB").
 */
export function formatBytes(bytes: number, decimals = 1): string {
  if (bytes === 0) return '0 B';
  if (bytes < 0) return `-${formatBytes(-bytes, decimals)}`;

  const k = 1024;
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  const unitIndex = Math.min(i, UNITS.length - 1);
  const value = bytes / Math.pow(k, unitIndex);

  return `${value.toFixed(decimals)} ${UNITS[unitIndex]}`;
}
