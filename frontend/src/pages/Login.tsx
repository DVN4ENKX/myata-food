import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/state/AuthContext'
import { Button, Field, Input, Toasts, useToasts } from '@/components/ui'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const toasts = useToasts()
  const [mode, setMode] = useState<'password' | 'pin'>('password')
  const [username, setUsername] = useState('admin')
  const [secret, setSecret] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    try {
      await login(username.trim(), secret, mode === 'pin')
      toasts.ok('Добро пожаловать')
      navigate('/', { replace: true })
    } catch (e) {
      toasts.error(e instanceof Error ? e.message : 'Не удалось войти')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <Toasts items={toasts.items} />
      <form className="login-card" onSubmit={submit}>
        <h1>Myata Food</h1>
        <p className="muted">Вход для сотрудников</p>

        <Field label="Логин">
          <Input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </Field>

        <Field label={mode === 'pin' ? 'PIN' : 'Пароль'}>
          <Input
            type="password"
            inputMode={mode === 'pin' ? 'numeric' : 'text'}
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            autoComplete={mode === 'pin' ? 'off' : 'current-password'}
            required
          />
        </Field>

        <Button variant="primary" type="submit" disabled={busy}>
          {busy ? 'Проверяем…' : 'Войти'}
        </Button>

        <button
          type="button"
          className="link"
          onClick={() => {
            setMode(mode === 'pin' ? 'password' : 'pin')
            setSecret('')
          }}
        >
          {mode === 'pin' ? 'Войти по паролю' : 'Войти по PIN (официант)'}
        </button>
      </form>
    </div>
  )
}
