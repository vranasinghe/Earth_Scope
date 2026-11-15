// Display helpers for background analysis jobs.

import type { Job, JobStatus } from '../types/jobs'

export const STATUS_TEXT: Record<JobStatus, string> = {
  PENDING: 'Waiting for the queue',
  QUEUED: 'Queued',
  RUNNING: 'Running',
  RETRYING: 'Retrying automatically',
  CANCEL_REQUESTED: 'Cancelling…',
  CANCELLED: 'Cancelled',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
  EXPIRED: 'Expired',
}

export function variableLabel(j: Job): string {
  return `${j.variable_id.replace(/_/g, ' ')} (${j.parameter})`
}

/** Ask before cancelling work that is already running (a queued job loses nothing). */
export function confirmCancel(job: Job): boolean {
  if (job.status === 'QUEUED' || job.status === 'PENDING') return true
  return window.confirm(
    `Cancel the analysis of ${job.area.name}? Processing stops at the next safe checkpoint. Verified NASA tiles are kept, so it can be retried later.`,
  )
}
