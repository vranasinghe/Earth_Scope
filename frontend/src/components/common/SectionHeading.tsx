import type { ReactNode } from 'react'

/** Section title + optional one-line description and trailing action. The title carries the section; no kicker labels. */
export function SectionHeading({
  title,
  description,
  action,
  id,
}: {
  title: string
  description?: ReactNode
  action?: ReactNode
  id?: string
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
      <div className="min-w-0">
        <h2 id={id} className="text-xl font-bold sm:text-[1.375rem]">
          {title}
        </h2>
        {description && <p className="measure mt-1 text-[0.9375rem] text-fg-muted">{description}</p>}
      </div>
      {action}
    </div>
  )
}
