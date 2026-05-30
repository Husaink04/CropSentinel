import { createContext, useCallback, useContext, useMemo, useState } from 'react'

const PageContext = createContext(null)

export function PageContextProvider({ children }) {
  const [contextLabel, setContextLabel] = useState('')
  const [contextMeta, setContextMeta] = useState('')

  const setPageContext = useCallback((label = '', meta = '') => {
    setContextLabel(label || '')
    setContextMeta(meta || '')
  }, [])

  const clearPageContext = useCallback(() => {
    setContextLabel('')
    setContextMeta('')
  }, [])

  const value = useMemo(
    () => ({ contextLabel, contextMeta, setPageContext, clearPageContext }),
    [contextLabel, contextMeta, setPageContext, clearPageContext],
  )

  return <PageContext.Provider value={value}>{children}</PageContext.Provider>
}

export function usePageContext() {
  const ctx = useContext(PageContext)
  if (!ctx) {
    return {
      contextLabel: '',
      contextMeta: '',
      setPageContext: () => {},
      clearPageContext: () => {},
    }
  }
  return ctx
}
