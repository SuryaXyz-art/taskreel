import { jsx, jsxs } from 'react/jsx-runtime'
import { useEffect, useState } from 'react'

function rowMark(ok) {
  if (ok === true) return 'ok'
  if (ok === false) return 'fail'
  return '·'
}

function Pane({ rest }) {
  const [data, setData] = useState({
    phase: 'idle',
    routine: null,
    message: 'Waiting for the agent.',
    steps: []
  })

  useEffect(() => {
    let stop = false
    const tick = () => {
      Promise.resolve(rest('/status'))
        .then(next => {
          if (!stop && next && typeof next === 'object') setData(next)
        })
        .catch(() => {})
    }
    tick()
    const id = setInterval(tick, 1500)
    return () => {
      stop = true
      clearInterval(id)
    }
  }, [rest])

  const steps = Array.isArray(data.steps) ? data.steps : []
  return jsxs('div', {
    className: 'flex h-full flex-col gap-2 p-3 text-sm',
    children: [
      jsx('div', { className: 'font-medium', children: 'Taskreel' }),
      jsx('div', {
        className: 'text-(--ui-text-tertiary)',
        children: data.routine ? `${data.phase} · ${data.routine}` : data.phase || 'idle'
      }),
      jsx('div', { children: data.message || '' }),
      jsx('ol', {
        className: 'm-0 flex list-decimal flex-col gap-1 pl-4',
        children: steps.map((step, index) =>
          jsx(
            'li',
            {
              children: `${rowMark(step && step.ok)} ${step && step.tool ? step.tool : 'step'} — ${
                step && step.summary ? step.summary : ''
              }`
            },
            index
          )
        )
      })
    ]
  })
}

export default {
  id: 'taskreel',
  name: 'Taskreel',
  register(ctx) {
    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'Taskreel',
      data: { placement: 'right', width: '320px' },
      render: () => jsx(Pane, { rest: path => ctx.rest(path) })
    })
  }
}
