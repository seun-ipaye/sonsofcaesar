import NavButton from "../NavButton";
import { useGo } from "../Site";
import "./Home.css";

export default function Home() {
  const go = useGo();

  return (
    <section className="home">
      <img
        className="home-photo"
        src="/images/home.jpg"
        alt="Sons of Caesar at On Deck"
      />
      <div className="home-text">
        <p>
          Sons of Caesar is an entertainment group based in Windsor Ontario. It
          started in March 2026 when we threw a party for no reason. Who needs a
          reason to party?
        </p>
        <div className="home-buttons">
          <button className="enter" onClick={() => go("gallery")}>
            see our events
          </button>
          <NavButton page="tickets" className="enter" onGo={go} />
        </div>
      </div>
    </section>
  );
}
