import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

type Toast = { id: number; msg: string; err?: boolean }
const Ctx = createContext<(msg: string, err?: boolean) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [t, setT] = useState<Toast | null>(null)
  const show = useCallback((msg: string, err?: boolean) => {
    const id = Date.now()
    setT({ id, msg, err })
    setTimeout(() => setT((cur) => (cur?.id === id ? null : cur)), 3600)
  }, [])
  return (
    <Ctx.Provider value={show}>
      {children}
      {t && <div className={'toast' + (t.err ? ' err' : '')} role="status">{t.msg}</div>}
    </Ctx.Provider>
  )
}

export const useToast = () => useContext(Ctx)
