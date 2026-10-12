import { useCallback, useEffect, useState } from 'react'

/* Единый хук загрузки: { data, err, loading, reload }.
   loader — async-функция без аргументов (замыкание на параметры).
   Ошибку не глотаем: err выставляется, страница решает — ErrorState/тост.
   Логика и API не меняются — только унификация loading/err/reload. */
export function useLoad(loader, deps = []) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(true)

  const reload = useCallback(() => {
    setErr(null)
    setLoading(true)
    return Promise.resolve()
      .then(loader)
      .then((d) => {
        setData(d)
        setLoading(false)
        return d
      })
      .catch((e) => {
        setErr(e)
        setLoading(false)
        throw e
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    let on = true
    setLoading(true)
    Promise.resolve()
      .then(loader)
      .then((d) => { if (on) { setData(d); setErr(null); setLoading(false) } })
      .catch((e) => { if (on) { setErr(e); setLoading(false) } })
    return () => { on = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, err, loading, reload }
}

export default useLoad
