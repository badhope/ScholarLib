import { Check, Clock, FileText, Search, ThumbsUp, BookOpen } from 'lucide-react'
import type { SubmissionStatus } from '@/lib/types'

interface WorkflowTimelineProps {
  status: SubmissionStatus
  submittedAt: Date
  reviewedAt: Date | null
}

interface StepDef {
  key: string
  label: string
  icon: React.ComponentType<{ className?: string }>
}

const STEPS: StepDef[] = [
  { key: 'submitted', label: 'Submitted', icon: FileText },
  { key: 'under_review', label: 'Under Review', icon: Search },
  { key: 'decision', label: 'Decision', icon: ThumbsUp },
  { key: 'published', label: 'Published', icon: BookOpen },
]

/**
 * Map a submission status to a step index (0–3) and indicate whether the
 * workflow has reached a terminal rejection (no Published step).
 */
function resolveStep(status: SubmissionStatus): { current: number; rejected: boolean } {
  switch (status) {
    case 'pending':
      return { current: 0, rejected: false }
    case 'resubmitted':
    case 'under_review':
      return { current: 1, rejected: false }
    case 'major_revision':
    case 'minor_revision':
      return { current: 2, rejected: false }
    case 'accepted':
    case 'approved':
      return { current: 3, rejected: false }
    case 'rejected':
      return { current: 2, rejected: true }
    default:
      return { current: 0, rejected: false }
  }
}

function formatDate(d: Date | null): string {
  if (!d) return ''
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export default function WorkflowTimeline({
  status,
  submittedAt,
  reviewedAt,
}: WorkflowTimelineProps) {
  const { current, rejected } = resolveStep(status)
  const stepCount = rejected ? 3 : 4
  const visibleSteps = STEPS.slice(0, stepCount)

  const getDate = (stepIndex: number): string => {
    if (stepIndex === 0) return formatDate(submittedAt)
    if (stepIndex >= 1 && reviewedAt) return formatDate(reviewedAt)
    return ''
  }

  return (
    <div className="rounded-md border p-4">
      <h4 className="mb-4 text-sm font-medium">Workflow</h4>

      {/* Desktop: horizontal timeline */}
      <div className="hidden sm:flex sm:items-start sm:gap-0">
        {visibleSteps.map((step, idx) => {
          const isCompleted = idx < current
          const isCurrent = idx === current
          const isFuture = idx > current

          const iconColor = isCompleted
            ? 'bg-primary text-primary-foreground'
            : isCurrent
              ? 'text-primary-foreground bg-primary'
              : 'text-muted-foreground bg-muted'

          const labelColor = isFuture
            ? 'text-muted-foreground'
            : 'text-foreground'

          const lineColor =
            idx < visibleSteps.length - 1
              ? isCompleted
                ? 'bg-primary'
                : 'bg-muted'
              : ''

          return (
            <div key={step.key} className="flex flex-1 flex-col items-center">
              <div className="flex w-full items-center">
                {/* Connector line left (except first) */}
                {idx > 0 && (
                  <div className={`h-0.5 flex-1 ${isCompleted || isCurrent ? 'bg-primary' : 'bg-muted'}`} />
                )}
                {/* Icon circle */}
                <div
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${iconColor}`}
                >
                  {isCompleted ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <step.icon className="h-4 w-4" />
                  )}
                </div>
                {/* Connector line right (except last) */}
                {idx < visibleSteps.length - 1 && (
                  <div className={`h-0.5 flex-1 ${lineColor}`} />
                )}
              </div>
              <div className="mt-2 text-center">
                <p className={`text-xs font-medium ${labelColor}`}>
                  {step.label}
                </p>
                {isCompleted && (
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    {getDate(idx)}
                  </p>
                )}
                {isCurrent && (
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    {getDate(idx) || 'Pending'}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Mobile: vertical timeline */}
      <div className="flex flex-col gap-0 sm:hidden">
        {visibleSteps.map((step, idx) => {
          const isCompleted = idx < current
          const isCurrent = idx === current
          const isFuture = idx > current

          const iconColor = isCompleted
            ? 'bg-primary text-primary-foreground'
            : isCurrent
              ? 'text-primary-foreground bg-primary'
              : 'text-muted-foreground bg-muted'

          const labelColor = isFuture
            ? 'text-muted-foreground'
            : 'text-foreground'

          return (
            <div key={step.key} className="flex gap-3">
              {/* Vertical line + icon column */}
              <div className="flex flex-col items-center">
                <div
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${iconColor}`}
                >
                  {isCompleted ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <step.icon className="h-4 w-4" />
                  )}
                </div>
                {idx < visibleSteps.length - 1 && (
                  <div
                    className={`mt-1 w-0.5 flex-1 ${
                      isCompleted ? 'bg-primary' : 'bg-muted'
                    }`}
                    style={{ minHeight: 24 }}
                  />
                )}
              </div>
              {/* Label + date */}
              <div className="pb-4 pt-1">
                <p className={`text-sm font-medium ${labelColor}`}>
                  {step.label}
                </p>
                {isCompleted && (
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {getDate(idx)}
                  </p>
                )}
                {isCurrent && (
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {getDate(idx) || (
                      <span className="inline-flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        Pending
                      </span>
                    )}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
