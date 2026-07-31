import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import { strings } from '../ui/strings'

const MARKDOWN_COMPONENTS: Components = {
  h1: (props) => <h1 className="mb-2 mt-4 text-lg font-semibold text-slate-100" {...props} />,
  h2: (props) => <h2 className="mb-2 mt-4 text-base font-semibold text-slate-100" {...props} />,
  h3: (props) => <h3 className="mb-1 mt-3 text-sm font-semibold text-slate-200" {...props} />,
  p: (props) => <p className="mb-2 text-sm leading-relaxed text-slate-300" {...props} />,
  ul: (props) => <ul className="mb-2 list-inside list-disc text-sm text-slate-300" {...props} />,
  ol: (props) => <ol className="mb-2 list-inside list-decimal text-sm text-slate-300" {...props} />,
  li: (props) => <li className="mb-1" {...props} />,
  strong: (props) => <strong className="font-semibold text-slate-100" {...props} />,
  code: (props) => <code className="rounded bg-slate-800 px-1 py-0.5 text-xs text-cyan-300" {...props} />,
  a: (props) => <a className="text-cyan-400 underline hover:text-cyan-300" {...props} />,
}

export function ReportView({ markdown }: { markdown: string }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    await navigator.clipboard.writeText(markdown)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function handleDownload() {
    const blob = new Blob([markdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'incident-report.md'
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          {strings.reportHeading}
        </h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleCopy}
            className="rounded bg-slate-800 px-3 py-1 text-xs font-medium text-slate-200 hover:bg-slate-700"
          >
            {copied ? strings.copiedLabel : strings.copyReportButton}
          </button>
          <button
            type="button"
            onClick={handleDownload}
            className="rounded bg-cyan-600 px-3 py-1 text-xs font-medium text-white hover:bg-cyan-500"
          >
            {strings.downloadReportButton}
          </button>
        </div>
      </div>

      <div className="rounded border border-slate-800 bg-slate-950 p-4">
        <ReactMarkdown components={MARKDOWN_COMPONENTS}>{markdown}</ReactMarkdown>
      </div>
    </div>
  )
}
