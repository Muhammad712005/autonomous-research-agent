import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import { useReactToPrint } from 'react-to-print'

// Maps agent names to Tailwind colour classes so the log feels alive
const AGENT_COLOURS = {
  manager:    'text-blue-400',
  researcher: 'text-yellow-400',
  writer:     'text-green-400',
  error:      'text-red-500',
  system:     'text-gray-500',
}

function agentColour(agent = '') {
  return AGENT_COLOURS[agent.toLowerCase()] ?? 'text-gray-300'
}

function App() {
  const [inputGoal, setInputGoal]         = useState('')
  const [isResearching, setIsResearching] = useState(false)
  const [logs, setLogs]                   = useState([])
  const [finalReport, setFinalReport]     = useState('')

  const socketRef    = useRef(null)
  const logBottomRef = useRef(null)
  const reportRef    = useRef(null)

  const handlePrint = useReactToPrint({
    contentRef: reportRef,
    documentTitle: 'Research_Report',
  })

  // Auto-scroll the log pane whenever new entries arrive
  useEffect(() => {
    logBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  // Clean up socket on unmount
  useEffect(() => {
    return () => socketRef.current?.close()
  }, [])

  function appendLog(agent, message) {
    setLogs(prev => [...prev, { agent, message }])
  }

  function handleResearchSubmit(e) {
    e.preventDefault()

    const goal = inputGoal.trim()
    if (!goal || isResearching) return

    setIsResearching(true)
    setLogs([])
    setFinalReport('')

    socketRef.current?.close()

    const wsUrl = import.meta.env.VITE_WS_URL || 'wss://muhammad-alam-autonomous-research-agentv2.hf.space/ws/research'
    const ws = new WebSocket(wsUrl)
    socketRef.current = ws

    ws.onopen = () => {
      appendLog('system', 'Connecting to research graph…')
      ws.send(goal)
      appendLog('system', `Goal dispatched: "${goal}"`)
    }

    ws.onmessage = (event) => {
      let payload
      try {
        payload = JSON.parse(event.data)
      } catch {
        appendLog('error', `Malformed server message: ${event.data}`)
        return
      }

      if (payload.type === 'log') {
        appendLog(payload.agent ?? 'system', payload.message ?? '')

      } else if (payload.type === 'result') {
        // Fallback shown if all formatting attempts fail
        let markdown = `### Raw Output\n\`\`\`json\n${JSON.stringify(payload.data, null, 2)}\n\`\`\``

        try {
          let report = payload.data
          if (typeof report === 'string') {
            report = JSON.parse(report)
          }

          if (report && typeof report === 'object') {
            const title    = String(report.title ?? 'Research Report')
            const abstract = String(report.abstract ?? report.executive_summary ?? '_No abstract provided._')
            const analysis = String(report.comprehensive_analysis ?? report.summary ?? '_No analysis provided._')

            // Strict Array.isArray guard before every .map() call
            const takeaways = Array.isArray(report.strategic_takeaways) ? report.strategic_takeaways
              : Array.isArray(report.key_findings) ? report.key_findings
              : []
            const sources   = Array.isArray(report.primary_sources) ? report.primary_sources
              : Array.isArray(report.sources_used) ? report.sources_used
              : []

            const takeawaysMd = takeaways.length
              ? takeaways.map(t => `- ${String(t)}`).join('\n')
              : '_No takeaways recorded._'

            const sourcesMd = sources.length
              ? sources.map(s => `- [${String(s)}](${String(s)})`).join('\n')
              : '_No sources recorded._'

            let md = `# ${title}\n\n`
            md += `## Abstract\n\n${abstract}\n\n`
            md += `## Comprehensive Analysis\n\n${analysis}\n\n`
            md += `## Strategic Takeaways\n\n${takeawaysMd}\n\n`
            md += `## Primary Sources\n\n${sourcesMd}\n\n`
            markdown = md
          }
        } catch (err) {
          console.error('Report formatting error:', err)
          markdown =
            `**Error formatting report:** ${err.message}\n\n` +
            `### Raw Data\n\`\`\`json\n${JSON.stringify(payload.data, null, 2)}\n\`\`\``
        }

        setFinalReport(typeof markdown === 'string' ? markdown : String(markdown))
        appendLog('system', 'Report received — graph reached END.')
        ws.close()

      } else if (payload.type === 'error') {
        appendLog('error', payload.message ?? 'Unknown server error.')
        ws.close()
      }
    }

    ws.onerror = () => {
      appendLog('error', 'WebSocket error — is the FastAPI server running on port 8000?')
      setIsResearching(false)
    }

    ws.onclose = (ev) => {
      if (!ev.wasClean) {
        appendLog('error', `Connection closed unexpectedly (code ${ev.code}).`)
      }
      setIsResearching(false)
    }
  }

  return (
    // Outer shell — font-sans for the overall app chrome
    <div className="min-h-screen bg-deepBlack text-gray-200 px-8 py-6 flex flex-col font-sans">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="mb-6 print:hidden">
        <h1 className="text-3xl font-bold tracking-widest uppercase text-crimson">
          Autonomous Research Agent
        </h1>
        <p className="text-xs text-gray-500 tracking-widest mt-1 uppercase">
          LangGraph · Playwright Stealth · Groq
        </p>
        <div className="mt-3 border-b border-[#2a0a0a]" />
      </header>

      {/* ── Split pane ─────────────────────────────────────────────────────── */}
      <div className="flex-1 flex gap-5 overflow-hidden min-h-0">

        {/* Left: Live Log — keeps font-mono for the terminal aesthetic */}
        <div className="w-1/3 bg-[#111111] border border-[#331111] rounded-lg p-4 flex flex-col overflow-hidden shadow-[0_0_18px_rgba(139,0,0,0.15)]">
          <p className="font-mono text-xs text-[#661111] uppercase tracking-widest mb-3 shrink-0">
            ◈ Agent Log
          </p>

          <div className="flex-1 overflow-y-auto space-y-1 font-mono text-sm">
            {logs.length === 0 && (
              <p className="text-gray-600 italic">Awaiting research goal…</p>
            )}
            {logs.map((entry, i) => (
              <div key={i} className="leading-snug">
                <span className={`font-bold mr-2 ${agentColour(entry?.agent ?? 'system')}`}>
                  [{(entry?.agent ?? 'system').toUpperCase()}]
                </span>
                <span className="text-gray-400">{entry?.message ?? ''}</span>
              </div>
            ))}
            <div ref={logBottomRef} />
          </div>

          {isResearching && (
            <div className="shrink-0 mt-3 flex items-center gap-2 font-mono text-xs text-[#8b0000]">
              <span className="animate-pulse">▌</span>
              <span>Processing…</span>
            </div>
          )}
        </div>

        {/* Right: Report Output */}
        <div className="w-2/3 bg-[#111111] border border-[#331111] rounded-lg p-6 overflow-y-auto shadow-[0_0_18px_rgba(139,0,0,0.1)] flex flex-col">

          <div className="flex items-center justify-between mb-4 shrink-0 print:hidden">
            <p className="text-xs text-[#661111] uppercase tracking-widest">◈ Final Report</p>

            {finalReport && (
              <button
                onClick={handlePrint}
                className="bg-[#5a0000] hover:bg-bloodRed text-white px-5 py-2 rounded font-semibold text-sm transition-all duration-200 hover:shadow-[0_0_12px_rgba(139,0,0,0.5)]"
              >
                ↓ Download PDF
              </button>
            )}
          </div>

          {finalReport ? (
            /* Report body — ref for printing. Screen: dark prose. Print: white academic paper. */
            <div
              ref={reportRef}
              className={[
                // Screen styles — dark prose with typography plugin
                'prose prose-invert max-w-none',
                'prose-headings:text-gray-100 prose-headings:font-bold',
                'prose-h1:text-2xl prose-h1:text-crimson prose-h1:border-b prose-h1:border-[#3a0000] prose-h1:pb-3',
                'prose-h2:text-lg prose-h2:text-gray-200 prose-h2:mt-6',
                'prose-h3:text-base prose-h3:text-gray-300',
                'prose-p:text-gray-300 prose-p:leading-relaxed',
                'prose-li:text-gray-300',
                'prose-a:text-crimson prose-a:no-underline hover:prose-a:underline',
                'prose-strong:text-gray-100',
                'prose-code:text-crimson prose-code:bg-[#1a0a0a] prose-code:px-1 prose-code:rounded',
                // Print overrides — whitepaper aesthetic
                'print:prose print:max-w-full print:bg-white print:p-12 print:font-serif',
                'print:text-black print:prose-headings:text-black',
                'print:prose-h1:text-4xl print:prose-h1:border-b-2 print:prose-h1:border-black print:prose-h1:pb-4 print:prose-h1:text-black',
                'print:prose-h2:text-2xl print:prose-h2:text-black',
                'print:prose-h3:text-xl print:prose-h3:text-black',
                'print:prose-p:text-black print:prose-li:text-black print:prose-a:text-black',
              ].join(' ')}
            >
              <ReactMarkdown>
                {typeof finalReport === 'string' ? finalReport : 'Error rendering report data.'}
              </ReactMarkdown>
            </div>
          ) : (
            <p className="text-gray-600 italic text-sm mt-2">
              {isResearching
                ? 'Waiting for Writer agent to synthesise findings…'
                : 'Submit a research goal below to generate a report.'}
            </p>
          )}
        </div>
      </div>

      {/* ── Input bar ──────────────────────────────────────────────────────── */}
      <form
        onSubmit={handleResearchSubmit}
        className="mt-5 flex print:hidden"
      >
        <input
          type="text"
          value={inputGoal}
          onChange={e => setInputGoal(e.target.value)}
          disabled={isResearching}
          placeholder="Enter your research goal and press Enter…"
          className="flex-1 bg-[#111111] border border-[#331111] focus:border-crimson focus:outline-none px-4 py-3 rounded-l text-gray-200 placeholder-gray-700 disabled:opacity-50 transition-colors"
        />
        <button
          type="submit"
          disabled={isResearching || !inputGoal.trim()}
          className="bg-bloodRed hover:bg-crimson text-white px-7 py-3 rounded-r font-semibold tracking-wide disabled:opacity-40 transition-all duration-200 hover:shadow-[0_0_12px_rgba(220,20,60,0.4)]"
        >
          {isResearching ? 'Running…' : 'Research'}
        </button>
      </form>

    </div>
  )
}

export default App
