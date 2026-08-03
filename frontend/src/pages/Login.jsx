import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';

const THEMES = {
  'Client User': {
    color: '#8b9097',
    soft: 'rgba(139,144,151,.15)',
    title: 'Welcome Back',
    subtitle: 'Sign in to access NOVA+ Power Transmission Intelligence Platform.',
  },
  Admin: {
    color: '#46474a',
    soft: 'rgba(70,71,74,.15)',
    title: 'Admin Portal',
    subtitle: 'Sign in to manage NOVA+ administration and platform controls.',
  },
};

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loginAs, setLoginAs] = useState('Client User');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const theme = THEMES[loginAs];

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const user = await login(email, password, loginAs);
      navigate(user.role === 'Admin' ? '/admin' : '/dashboard', { replace: true });
    } catch (err) {
      setError(err.message || 'Invalid email or password.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <nav style={styles.navbar}>
        <Link to="/" style={styles.navBrand}>
          <svg style={styles.navBrandMark} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="8" y="9" width="8" height="7" rx="2" stroke="currentColor" strokeWidth="1.4" />
            <circle cx="11" cy="12" r="0.9" fill="currentColor" />
            <circle cx="13" cy="12" r="0.9" fill="currentColor" />
            <path d="M11 14C11.5 14.6 12.5 14.6 13 14" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            <path d="M8 10L5.5 8.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            <path d="M16 10L18.5 8.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            <path d="M8 15L5.5 16.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            <path d="M16 15L18.5 16.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            <circle cx="5.2" cy="8.2" r="0.8" fill="currentColor" />
            <circle cx="18.8" cy="8.2" r="0.8" fill="currentColor" />
            <circle cx="5.2" cy="16.8" r="0.8" fill="currentColor" />
            <circle cx="18.8" cy="16.8" r="0.8" fill="currentColor" />
            <path d="M9 18H15" stroke="currentColor" strokeWidth="1" opacity="0.3" strokeLinecap="round" />
          </svg>
          DROGO AEROSPACE
        </Link>
        <ul style={styles.navActions}>
          <li><Link to="/" style={styles.navLink}>Home</Link></li>
        </ul>
      </nav>

      <div style={styles.wrapper}>
        <div style={styles.overlay} />

        <form onSubmit={handleSubmit} style={{ ...styles.card, '--theme': theme.color, '--theme-soft': theme.soft }}>
          <h1 style={styles.title}>{theme.title}</h1>
          <p style={styles.subtitle}>{theme.subtitle}</p>

          {error && <div style={styles.errorMsg}>{error}</div>}

          <div style={{ ...styles.roleCard, borderColor: theme.color, background: theme.soft }}>
            <div style={styles.roleToggle}>
              <div
                style={{
                  ...styles.roleToggleIndicator,
                  background: theme.color,
                  transform: loginAs === 'Admin' ? 'translateX(100%)' : 'translateX(0)',
                }}
              />
              {['Client User', 'Admin'].map(role => (
                <label
                  key={role}
                  style={{
                    ...styles.roleLabel,
                    color: loginAs === role ? '#fff' : '#676869',
                  }}
                >
                  <input
                    type="radio" name="login_as" value={role} checked={loginAs === role}
                    onChange={() => setLoginAs(role)} style={{ display: 'none' }}
                  />
                  {role === 'Client User' ? 'Client' : 'Admin'}
                </label>
              ))}
            </div>

            <div style={styles.inputGroup}>
              <label style={styles.inputLabel}>Email</label>
              <input
                type="email" required value={email} onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com" style={styles.input}
              />
            </div>

            <div style={styles.inputGroup}>
              <label style={styles.inputLabel}>Password</label>
              <input
                type="password" required value={password} onChange={e => setPassword(e.target.value)}
                placeholder="••••••••" style={styles.input}
              />
            </div>

            <button type="submit" disabled={submitting} style={{ ...styles.loginBtn, background: theme.color }}>
              {submitting ? 'Signing in…' : 'Sign In'}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

const styles = {
  navbar: {
    position: 'fixed', top: 0, left: 0, right: 0, zIndex: 50,
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '16px 40px',
    background: 'rgba(255,255,255,.7)', backdropFilter: 'blur(14px)',
    borderBottom: '1px solid rgba(0,0,0,.05)',
  },
  navBrand: {
    display: 'flex', alignItems: 'center', gap: 10,
    textDecoration: 'none', color: '#2f3640',
    fontSize: 15, fontWeight: 700, letterSpacing: 1,
  },
  navBrandMark: { width: 28, height: 28, color: '#7dc7f7', flexShrink: 0 },
  navActions: { listStyle: 'none', display: 'flex', alignItems: 'center', gap: 28 },
  navLink: { textDecoration: 'none', color: '#555', fontSize: 14, fontWeight: 600 },

  wrapper: {
    minHeight: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center',
    position: 'relative', padding: '90px 20px 30px',
    backgroundImage: 'url(/static/images/login.png)',
    backgroundSize: 'cover', backgroundPosition: 'center center', backgroundRepeat: 'no-repeat',
  },
  overlay: { position: 'absolute', inset: 0, backdropFilter: 'blur(6px)' },

  card: {
    position: 'relative', zIndex: 2, width: '100%', maxWidth: 380,
    background: 'rgba(255,255,255,0.2)', backdropFilter: 'blur(10px)',
    borderRadius: 22, padding: 34, boxShadow: '0 20px 50px rgba(0,0,0,.12)',
  },
  title: { fontSize: 28, fontWeight: 700, color: '#333', marginBottom: 8 },
  subtitle: { color: '#666', fontSize: 13.5, lineHeight: 1.5, marginBottom: 22 },

  errorMsg: {
    background: '#fdeaea', color: '#c0392b', border: '1px solid #f3c4c4',
    borderRadius: 10, padding: '10px 12px', marginBottom: 18, fontSize: 13,
  },

  roleCard: { border: '1px solid', borderRadius: 16, padding: '14px 16px 16px', marginBottom: 22 },
  roleToggle: {
    position: 'relative', display: 'flex', background: '#fff',
    borderRadius: 12, padding: 3, marginBottom: 16,
  },
  roleToggleIndicator: {
    position: 'absolute', top: 3, left: 3,
    width: 'calc(50% - 4px)', height: 'calc(100% - 6px)',
    borderRadius: 9, boxShadow: '0 2px 8px rgba(0,0,0,.08)',
    transition: 'all .3s ease',
  },
  roleLabel: {
    flex: 1, textAlign: 'center', padding: 10, cursor: 'pointer',
    zIndex: 1, fontWeight: 600, fontSize: 14, userSelect: 'none',
  },

  inputGroup: { marginBottom: 16 },
  inputLabel: { display: 'block', marginBottom: 6, color: '#555', fontSize: 13 },
  input: {
    width: '100%', padding: '12px 14px', border: '1px solid #dfe4ea',
    borderRadius: 11, fontSize: 14, outline: 'none', background: '#fff',
  },

  loginBtn: {
    width: '100%', height: 50, border: 'none', borderRadius: 13,
    color: '#fff', fontSize: 15, fontWeight: 600, marginTop: 4, cursor: 'pointer',
  },
};
