const INSTAGRAM = 'https://instagram.com/socfrvr'

export default function Footer() {
  return (
    <footer className="footer">
      <span>
        © {new Date().getFullYear()} Sons of Caesar · <a href="/privacy">privacy</a>
      </span>
      <a href={INSTAGRAM} target="_blank" rel="noreferrer" aria-label="Instagram @socfrvr">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8">
          <rect x="3" y="3" width="18" height="18" rx="5" />
          <circle cx="12" cy="12" r="4" />
          <circle cx="17.5" cy="6.5" r="0.8" fill="currentColor" stroke="none" />
        </svg>
      </a>
    </footer>
  )
}
