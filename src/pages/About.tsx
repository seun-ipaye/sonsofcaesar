import { parties } from "../data/parties";
import "./About.css";

// Placeholder: swap for a specific photo once you pick one
const onDeckPhoto = parties.find((p) => p.slug === "on-deck")?.photos[1];

export default function About() {
  return (
    <article className="about">
      <section className="chapter">
        <p>
          Sons of Caesar was founded by 4 boys in Lagos, Nigeria. We started off
          as a clothing brand in 2021. After four successful drops, we stopped
          making clothes to focus on college applications and graduation.
        </p>
      </section>

      <div className="about-photos pair">
        <img
          src="/images/lagos-1.jpg"
          alt="Sons of Caesar tee, red bandana"
          loading="lazy"
        />
        <img
          src="/images/lagos-2.jpg"
          alt="Sons of Caesar tee, purple bandana"
          loading="lazy"
        />
      </div>

      <section className="chapter">
        <p>
          In 2026, we rebranded as an entertainment group. It started in March
          when we threw a party for no reason. Who needs a reason to party?
        </p>
      </section>

      {onDeckPhoto && (
        <div className="about-photos single">
          <img
            src={onDeckPhoto.full}
            alt="On Deck, March 2026"
            loading="lazy"
          />
        </div>
      )}

      <section className="chapter">
        <p>the rest</p>
      </section>
    </article>
  );
}
