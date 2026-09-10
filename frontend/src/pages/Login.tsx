import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { Icon } from '../ui'

export default function LoginPage() {
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      await api.post('/api/login', { password })
      navigate('/')
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? 'Incorrect password.' : 'Login failed - is the server running?')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-chrome-900 flex items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2.5 justify-center mb-6">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-primary to-violet flex items-center justify-center text-white">
            <Icon name="bolt" className="!text-[20px]" />
          </div>
          <div>
            <div className="text-white font-semibold text-lg leading-tight">Outreach Command</div>
            <div className="text-chrome-400 text-[11px] font-mono">SALES NAV CORE · OPS v2.4</div>
          </div>
        </div>
        <form onSubmit={submit} className="card p-6" aria-labelledby="login-heading">
          <h1 id="login-heading" className="text-slate-900 font-semibold mb-1">Sign in</h1>
          <p className="text-slate-500 mb-4">Internal ops tool. Enter the admin password.</p>
          <label htmlFor="password" className="block text-th uppercase text-slate-500 mb-1.5">Admin password</label>
          <input
            id="password" type="password" autoComplete="current-password" required
            className="input" value={password} onChange={e => setPassword(e.target.value)}
            placeholder="••••••••••••" autoFocus
          />
          {error && <p className="mt-2 text-crit-text text-[12px]" role="alert">{error}</p>}
          <button type="submit" className="btn-primary w-full justify-center mt-4 h-9" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
