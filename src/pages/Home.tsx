import NavButton from '../NavButton'
import { useGo } from '../Site'
import './Home.css'

export default function Home() {
  const go = useGo()

  return (
    <section className="home">
      <img className="home-photo" src="/images/home.jpg" alt="Sons of Caesar at On Deck" />
      <div className="home-text">
        <p>
          Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor
          incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud
          exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure
          dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur.
        </p>
        <div className="home-buttons">
          <button className="enter" onClick={() => go('gallery')}>
            see our events
          </button>
          <NavButton page="tickets" className="enter" onGo={go} />
        </div>
      </div>
    </section>
  )
}
