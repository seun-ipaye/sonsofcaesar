// The secret address, shown under ticket holders' QR codes
export default function SecretAddress({ address }: { address?: string | null }) {
  if (!address) return null
  const maps = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`
  return (
    <div className="secret-address">
      <div className="secret-address-label">address</div>
      <div className="secret-address-text">{address}</div>
      <a href={maps} target="_blank" rel="noreferrer">
        open in maps
      </a>
      <p>Please keep it to ticket holders.</p>
    </div>
  )
}
