import { useRef, useState } from 'react'
import { strings } from '../ui/strings'

export function EvidenceUpload({
  files,
  disabled,
  onUpload,
}: {
  files: string[]
  disabled: boolean
  onUpload: (file: File) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  function handleFiles(fileList: FileList | null) {
    if (!fileList) return
    for (const file of fileList) onUpload(file)
  }

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
        {strings.evidenceHeading}
      </h3>
      {disabled ? (
        <p className="text-xs text-slate-500">{strings.evidenceClosedHint}</p>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(event) => {
            event.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragOver(false)
            handleFiles(event.dataTransfer.files)
          }}
          className={`w-full rounded border-2 border-dashed px-4 py-6 text-sm transition-colors ${
            dragOver
              ? 'border-cyan-500 bg-cyan-500/5 text-cyan-300'
              : 'border-slate-700 text-slate-500 hover:border-slate-600'
          }`}
        >
          {strings.evidenceDropHint}
        </button>
      )}
      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(event) => handleFiles(event.target.files)}
      />
      {files.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 text-xs font-semibold text-slate-500">
            {strings.evidenceUploadedListHeading}
          </p>
          <ul className="space-y-1">
            {files.map((name, index) => (
              <li
                key={`${name}-${index}`}
                className="rounded bg-slate-950 px-2 py-1 text-xs text-slate-300"
              >
                {name}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
