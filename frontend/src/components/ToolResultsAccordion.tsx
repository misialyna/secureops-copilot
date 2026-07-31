import type { ToolResult } from '../api/types'
import { strings } from '../ui/strings'

function ToolResultItem({ result }: { result: ToolResult }) {
  return (
    <details className="rounded border border-slate-800 bg-slate-950 open:border-slate-700">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-slate-200">
        {result.tool_name}
        <span className="ml-2 font-normal text-slate-500">{result.summary}</span>
      </summary>
      <div className="space-y-2 border-t border-slate-800 px-3 py-2 text-xs">
        {result.findings.length > 0 && (
          <div>
            <p className="mb-1 font-semibold text-slate-500">{strings.toolFindingsHeading}</p>
            <pre className="overflow-x-auto rounded bg-slate-900 p-2 text-slate-300">
              {JSON.stringify(result.findings, null, 2)}
            </pre>
          </div>
        )}
        {result.warnings.length > 0 && (
          <div>
            <p className="mb-1 font-semibold text-amber-500">{strings.toolWarningsHeading}</p>
            <ul className="list-inside list-disc text-amber-300">
              {result.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  )
}

export function ToolResultsAccordion({ results }: { results: ToolResult[] }) {
  if (results.length === 0) return null
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
        {strings.toolResultsHeading}
      </h2>
      <div className="space-y-2">
        {results.map((result, index) => (
          <ToolResultItem key={`${result.tool_name}-${index}`} result={result} />
        ))}
      </div>
    </div>
  )
}
