import { useMemo, useState, useEffect, useRef } from "react";
import logo from "./assets/mymile-logo.png";
import egyptTravelImage from "./imports/20__Europe_Travel_Bucket_List_Tips_You_Need_for_an_Unforgettable_Adventure.jpg";
import editorHeroImage from "./imports/editor-hero-egypt.jpg";
import editorLoginImage from "./imports/editor-login-egypt.jpg";
import signupImage from "./imports/download__2_.jpg";
import { AgGridHotelComparison } from "./components/AgGridHotelComparison";
import { AgGridBudgetTable } from "./components/AgGridBudgetTable";
import { ShoppingCartDrawer } from "./components/ShoppingCartDrawer";
import { ApimaticModal } from "./components/ApimaticModal";
import { api, getStoredToken, getStoredUser, getErrorMessage } from "./services/api";
import { TripPlan, Hotel, Product, CartItem, User, BudgetBreakdown } from "./types";

type View =
  | "home"
  | "plan"
  | "results"
  | "trips"
  | "pricing"
  | "profile"
  | "login"
  | "signup"
  | "assistant"
  | "shop";

type IconName =
  | "arrow"
  | "spark"
  | "pin"
  | "calendar"
  | "users"
  | "cloud"
  | "hotel"
  | "bag"
  | "wallet"
  | "route"
  | "check"
  | "star"
  | "send"
  | "menu"
  | "close"
  | "chevron"
  | "clock"
  | "shield"
  | "heart"
  | "code";

const heroImage =
  "https://images.unsplash.com/photo-1769842003846-a4f6c1838fc8?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=85&w=1400";

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, React.ReactNode> = {
    arrow: (
      <>
        <path d="M5 12h14" />
        <path d="m13 6 6 6-6 6" />
      </>
    ),
    spark: (
      <>
        <path d="m12 3-1.2 3.8L7 8l3.8 1.2L12 13l1.2-3.8L17 8l-3.8-1.2L12 3Z" />
        <path d="m5 14-.7 2.3L2 17l2.3.7L5 20l.7-2.3L8 17l-2.3-.7L5 14Z" />
      </>
    ),
    pin: (
      <>
        <path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z" />
        <circle cx="12" cy="10" r="2.5" />
      </>
    ),
    calendar: (
      <>
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M16 3v4M8 3v4M3 10h18" />
      </>
    ),
    users: (
      <>
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8" />
      </>
    ),
    cloud: <path d="M17.5 19H7a5 5 0 1 1 1.6-9.7A6 6 0 0 1 20 12a3.5 3.5 0 0 1-2.5 7Z" />,
    hotel: (
      <>
        <path d="M4 21V4a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v17M2 21h20M8 7h2M14 7h2M8 11h2M14 11h2M10 21v-5h4v5" />
      </>
    ),
    bag: (
      <>
        <path d="M6 8h12l1 13H5L6 8Z" />
        <path d="M9 9V6a3 3 0 0 1 6 0v3" />
      </>
    ),
    wallet: (
      <>
        <rect x="3" y="5" width="18" height="15" rx="3" />
        <path d="M16 12h5v4h-5a2 2 0 0 1 0-4Z" />
      </>
    ),
    route: (
      <>
        <circle cx="6" cy="19" r="2" />
        <circle cx="18" cy="5" r="2" />
        <path d="M8 19h3a3 3 0 0 0 3-3v-2a3 3 0 0 0-3-3H9a3 3 0 0 1-3-3V7M16 5h-3" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    star: (
      <path d="m12 2.8 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.4l6.2-.9L12 2.8Z" />
    ),
    send: (
      <>
        <path d="m22 2-7 20-4-9-9-4 20-7Z" />
        <path d="M22 2 11 13" />
      </>
    ),
    menu: (
      <>
        <path d="M4 7h16M4 12h16M4 17h16" />
      </>
    ),
    close: (
      <>
        <path d="m6 6 12 12M18 6 6 18" />
      </>
    ),
    chevron: <path d="m9 18 6-6-6-6" />,
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    shield: (
      <>
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
        <path d="m9 12 2 2 4-4" />
      </>
    ),
    heart: (
      <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z" />
    ),
    code: (
      <>
        <polyline points="16 18 22 12 16 6" />
        <polyline points="8 6 2 12 8 18" />
      </>
    )
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] || paths.spark}
    </svg>
  );
}

function Logo({ onClick }: { onClick: () => void }) {
  return (
    <button className="logo-wrap" onClick={onClick} aria-label="MYMILE home">
      <img src={logo} alt="MYMILE" />
    </button>
  );
}

// "Alex Morgan" -> "AM", "Reem" -> "RE"
function getInitials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function UserMenu({
  user,
  go,
  onLogout,
}: {
  user: User;
  go: (v: View) => void;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const pick = (fn: () => void) => {
    setOpen(false);
    fn();
  };

  return (
    <div className="user-menu" ref={ref}>
      <button
        className="user-avatar"
        onClick={() => setOpen(!open)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${user.name}`}
        title={user.name}
      >
        {getInitials(user.name)}
      </button>
      {open && (
        <div className="user-dropdown" role="menu">
          <div className="user-dropdown-head">
            <b>{user.name}</b>
            <small>{user.email}</small>
          </div>
          <button role="menuitem" onClick={() => pick(() => go("profile"))}>
            Profile
          </button>
          <button role="menuitem" onClick={() => pick(() => go("trips"))}>
            My trips
          </button>
          <button role="menuitem" className="logout" onClick={() => pick(onLogout)}>
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

function Header({
  view,
  setView,
  authUser,
  onLogout,
}: {
  view: View;
  setView: (v: View) => void;
  authUser: User | null;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const go = (v: View) => {
    setView(v);
    setOpen(false);
    window.scrollTo(0, 0);
  };

  return (
    <header className="site-header">
      <div className="nav-shell">
        <Logo onClick={() => go("home")} />
        <nav className={open ? "main-nav open" : "main-nav"} aria-label="Main navigation">
          {[
            ["home", "Home"],
            ["plan", "Plan a trip"],
            ["trips", "My trips"],
            ["results", "Explore"],
            ["pricing", "Pricing"],
            ["profile", "Profile"],
          ].map(([id, label]) => (
            <button key={id} className={view === id ? "active" : ""} onClick={() => go(id as View)}>
              {label}
            </button>
          ))}
          {authUser ? (
            <button
              className="mobile-login"
              onClick={() => {
                setOpen(false);
                onLogout();
              }}
            >
              Log out ({authUser.name})
            </button>
          ) : (
            <>
              <button className="mobile-login" onClick={() => go("login")}>
                Log in
              </button>
              <button className="mobile-login" onClick={() => go("signup")}>
                Sign up
              </button>
            </>
          )}
        </nav>

        <div className="nav-actions">
          {!authUser && (
            <>
              <button
                className={view === "login" ? "text-btn active" : "text-btn"}
                onClick={() => go("login")}
              >
                Log in
              </button>
              <button
                className={`btn btn-secondary btn-small signup-btn${view === "signup" ? " active" : ""}`}
                onClick={() => go("signup")}
              >
                Sign up
              </button>
            </>
          )}
          <button
            className="btn btn-primary whitespace-nowrap min-w-[150px] px-6 py-2.5 text-sm font-bold"
            onClick={() => go("plan")}
          >
            Plan my trip <Icon name="arrow" size={16} />
          </button>
          {authUser && <UserMenu user={authUser} go={go} onLogout={onLogout} />}
        </div>
        <button className="menu-btn" onClick={() => setOpen(!open)} aria-label="Toggle menu">
          <Icon name={open ? "close" : "menu"} />
        </button>
      </div>
    </header>
  );
}

const features = [
  ["spark", "AI trip planning", "A journey shaped around your pace, interests, and travel style."],
  ["hotel", "Stays that fit you", "Handpicked hotels with clear reasons why each one matches."],
  ["cloud", "Weather-wise plans", "Daily forecasts shape your itinerary and packing list."],
  ["bag", "Travel essentials", "Smart product picks via Channel3 for your destination & season."],
  ["wallet", "Budget optimization", "See where every dollar goes and make confident trade-offs."],
  ["route", "One connected journey", "Interactive AG Grid dashboards and APIMatic developer APIs."],
] as [IconName, string, string][];

function Home({ go, onOpenApimatic }: { go: (v: View) => void; onOpenApimatic: () => void }) {
  return (
    <main>
      <section className="hero">
        <div className="hero-orbit orbit-one" />
        <div className="hero-orbit orbit-two" />
        <div className="page-shell hero-grid">
          <div className="hero-copy">
            <div className="eyebrow">
              <Icon name="spark" size={16} /> Your AI travel companion
            </div>
            <h1>
              YOUR SMILE,
              <br />
              <span>EVERY MILE.</span>
            </h1>
            <p>
              Tell us how you want to travel. MYMILE finds the right stays, builds your itinerary, checks the weather, and helps every mile fit your budget.
            </p>
            <div className="hero-actions">
              <button className="btn btn-primary" onClick={() => go("plan")}>
                Plan my trip <Icon name="arrow" size={18} />
              </button>
              <button
                className="btn btn-secondary"
                onClick={() =>
                  document.getElementById("features")?.scrollIntoView({ behavior: "smooth" })
                }
              >
                Explore features
              </button>
              <button
                className="btn btn-light"
                onClick={onOpenApimatic}
              >
                APIMatic SDKs <Icon name="code" size={16} />
              </button>
            </div>
            <div className="trust-row">
              <div className="avatars">
                <span>A</span>
                <span>M</span>
                <span>J</span>
              </div>
              <div>
                <b>
                  4.9 <span className="stars">★★★★★</span>
                </b>
                <small>Loved by 12,000+ happy travelers</small>
              </div>
            </div>
          </div>
          <div className="hero-visual">
            <div className="photo-frame">
              <img src={editorHeroImage} alt="Egyptian destination landscape" />
            </div>
            <div className="float-card weather-card">
              <span className="icon-box yellow">
                <Icon name="cloud" />
              </span>
              <div>
                <small>Egypt weather</small>
                <strong>
                  22° <em>Sunny</em>
                </strong>
              </div>
            </div>
            <div className="float-card plan-card">
              <span className="icon-box blue">
                <Icon name="spark" />
              </span>
              <div>
                <small>Your plan is ready</small>
                <strong>7 days in Egypt</strong>
                <span className="match">98% match</span>
              </div>
            </div>
            <div className="destination-tag">
              <Icon name="pin" size={17} />
              <div>
                <small>Next adventure</small>
                <b>Giza, Egypt</b>
              </div>
            </div>
          </div>
        </div>
        <div className="brand-strip">
          <span>Personalized for you</span>
          <i />
          <span>Powered by smart travel AI</span>
          <i />
          <span>Integrated with Channel3, AG Grid & APIMatic</span>
        </div>
      </section>

      <section className="section page-shell" id="features">
        <div className="section-heading">
          <div>
            <span className="kicker">ONE COMPANION, EVERY MILE</span>
            <h2>
              Everything you need to
              <br />
              travel <span>beautifully.</span>
            </h2>
          </div>
          <p>
            From the first spark of an idea to the moment you unpack, MYMILE brings every part of
            your journey together.
          </p>
        </div>
        <div className="feature-grid">
          {features.map(([icon, title, text], i) => (
            <article className={`feature-card feature-${i + 1}`} key={title}>
              <div className="feature-icon">
                <Icon name={icon} />
              </div>
              <h3>{title}</h3>
              <p>{text}</p>
              <span className="learn" onClick={() => go("plan")}>
                Explore <Icon name="arrow" size={15} />
              </span>
            </article>
          ))}
        </div>
      </section>

      <section className="how-section">
        <div className="page-shell how-grid">
          <div className="how-photo">
            <img src={egyptTravelImage} alt="Traveler exploring Egypt" />
            <div className="passport-stamp">
              M<br />
              <span>
                GO
                <br />
                FAR
              </span>
            </div>
          </div>
          <div className="how-copy">
            <span className="kicker">HOW IT WORKS</span>
            <h2>
              Your next journey,
              <br />
              made <span>effortless.</span>
            </h2>
            <p>
              Answer a few simple questions. Your AI companion handles the research and shapes it
              into a trip that feels entirely yours.
            </p>
            <div className="steps">
              {[
                [
                  "01",
                  "Tell us your travel dream",
                  "Destination, dates, people, and what makes a great trip for you.",
                ],
                [
                  "02",
                  "Let MYMILE think it through",
                  "We connect live weather, verified stays, activities, and Channel3 essentials.",
                ],
                [
                  "03",
                  "Explore with AG Grid",
                  "Compare stays and watch your budget balance recalculate in real-time.",
                ],
                [
                  "04",
                  "Enjoy every mile",
                  "Travel with an itinerary and companion that are always there when you need them.",
                ],
              ].map(([n, t, d]) => (
                <div className="step" key={n}>
                  <span>{n}</span>
                  <div>
                    <h3>{t}</h3>
                    <p>{d}</p>
                  </div>
                </div>
              ))}
            </div>
            <button className="btn btn-primary" onClick={() => go("plan")}>
              Create my travel plan <Icon name="arrow" size={17} />
            </button>
          </div>
        </div>
      </section>

      <section className="section page-shell">
        <div className="pricing-tease">
          <div>
            <span className="kicker yellow-text">TRAVEL YOUR WAY</span>
            <h2>
              Start free. Go further
              <br />
              with <span>Premium.</span>
            </h2>
            <p>
              Get a beautiful plan for free, or unlock smart budget optimization
              and deeper comparisons.
            </p>
            <button className="btn btn-light" onClick={() => go("pricing")}>
              Compare plans <Icon name="arrow" size={17} />
            </button>
          </div>
          <div className="mini-plan">
            <div className="plan-top">
              <span className="premium-pill">
                <Icon name="spark" size={14} /> PREMIUM
              </span>
              <b>
                $9<small>/month</small>
              </b>
            </div>
            {[
              "AI budget optimization",
              "Advanced hotel comparison",
              "Detailed expense breakdown",
              "Personalized booking links",
            ].map((x) => (
              <p key={x}>
                <Icon name="check" size={16} />
                {x}
              </p>
            ))}
          </div>
        </div>
      </section>

      <section className="final-cta">
        <div className="route-line" />
        <div className="page-shell final-cta-inner">
          <span className="kicker">WHERE TO NEXT?</span>
          <h2>
            Your next adventure
            <br />
            starts <span>here.</span>
          </h2>
          <p>Less searching. More discovering. A better journey is only a few details away.</p>
          <button className="btn btn-yellow" onClick={() => go("plan")}>
            Start planning <Icon name="arrow" size={17} />
          </button>
        </div>
      </section>
    </main>
  );
}

// Format a Date as YYYY-MM-DD in local time (what <input type="date"> expects).
function toDateInputValue(d: Date) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

const CURRENCIES = [
  { code: "USD", label: "USD ($)", symbol: "$" },
  { code: "EUR", label: "EUR (€)", symbol: "€" },
  { code: "GBP", label: "GBP (£)", symbol: "£" },
  { code: "EGP", label: "EGP (E£)", symbol: "E£" },
  { code: "SAR", label: "SAR (﷼)", symbol: "﷼" },
];

// Keep the traveler count a whole number between 1 and 50.
function clampTravelers(value: string) {
  const n = parseInt(value, 10);
  if (Number.isNaN(n)) return 1;
  return Math.min(50, Math.max(1, n));
}

function Planner({
  go,
  onGeneratePlan,
  isLoading,
  userPlan,
}: {
  go: (v: View) => void;
  onGeneratePlan: (data: any) => Promise<void>;
  isLoading: boolean;
  userPlan: 'free' | 'premium';
}) {
  const [step, setStep] = useState(1);
  const [destination, setDestination] = useState("Kyoto, Japan");
  const [departureDate, setDepartureDate] = useState(() => toDateInputValue(new Date()));
  const [returnDate, setReturnDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 5);
    return toDateInputValue(d);
  });
  const [purpose, setPurpose] = useState("Tourism");
  const [travelers, setTravelers] = useState("2");
  const [stayPreference, setStayPreference] = useState("Boutique hotel");
  const [priorities, setPriorities] = useState<string[]>(["Local culture", "Great food", "Slow pace"]);
  const [notes, setNotes] = useState("");
  const [premiumOptim, setPremiumOptim] = useState(userPlan === "premium");
  const [budgetVal, setBudgetVal] = useState("4500");
  const [currency, setCurrency] = useState("USD");

  const titles = ["Where are you headed?", "Who’s coming along?", "Make it feel like you"];

  const togglePriority = (tag: string) => {
    if (priorities.includes(tag)) {
      setPriorities(priorities.filter((p) => p !== tag));
    } else {
      setPriorities([...priorities, tag]);
    }
  };

  const handleFinish = async () => {
    await onGeneratePlan({
      destination,
      departure_date: departureDate,
      return_date: returnDate,
      travelers: clampTravelers(travelers),
      purpose,
      stay_preference: stayPreference,
      priorities,
      notes,
      plan: premiumOptim ? "premium" : "free",
      total_budget: premiumOptim ? parseFloat(budgetVal.replace(/,/g, "")) || 4500 : undefined,
    });
    go("results");
  };

  return (
    <main className="app-bg">
      <div className="planner-shell">
        <div className="progress-top">
          <button className="back-btn" onClick={() => (step > 1 ? setStep(step - 1) : go("home"))}>
            ← Back
          </button>
          <span>Step {step} of 3</span>
          <div className="progress-track">
            <i style={{ width: `${(step / 3) * 100}%` }} />
          </div>
        </div>

        <div className="planner-title">
          <span className="kicker">LET'S PLAN SOMETHING WONDERFUL</span>
          <h1>{titles[step - 1]}</h1>
          <p>
            {step === 1
              ? "Start with the basics. You can always change these details later."
              : step === 2
                ? "Tell us about your group and the reason for your journey."
                : "A few preferences help our AI Agent create a plan that fits your style."}
          </p>
        </div>

        <div className="planner-card">
          {step === 1 && (
            <div className="form-grid">
              <label className="field full">
                <span>
                  Destination <b>*</b>
                </span>
                <div className="input-wrap">
                  <Icon name="pin" />
                  <input
                    value={destination}
                    onChange={(e) => setDestination(e.target.value)}
                    placeholder="e.g. Kyoto, Paris, Cairo, Makkah"
                  />
                </div>
                <small>Try: Kyoto, Japan · Paris, France · Cairo, Egypt · Makkah, Saudi Arabia</small>
              </label>
              <label className="field">
                <span>
                  Departure date <b>*</b>
                </span>
                <div className="input-wrap">
                  <Icon name="calendar" />
                  <input
                    type="date"
                    value={departureDate}
                    onChange={(e) => setDepartureDate(e.target.value)}
                  />
                </div>
              </label>
              <label className="field">
                <span>
                  Return date <b>*</b>
                </span>
                <div className="input-wrap">
                  <Icon name="calendar" />
                  <input
                    type="date"
                    value={returnDate}
                    onChange={(e) => setReturnDate(e.target.value)}
                  />
                </div>
              </label>
            </div>
          )}

          {step === 2 && (
            <div>
              <label className="field">
                <span>What brings you there?</span>
              </label>
              <div className="choice-grid">
                {["Tourism", "Business", "Umrah", "Other"].map((x) => (
                  <button
                    className={purpose === x ? "choice active" : "choice"}
                    onClick={() => setPurpose(x)}
                    key={x}
                    type="button"
                  >
                    <Icon name={x === "Business" ? "bag" : x === "Tourism" ? "pin" : "route"} />
                    <b>{x}</b>
                  </button>
                ))}
              </div>
              <div className="form-grid spaced">
                <label className="field">
                  <span>Travelers</span>
                  <div className="input-wrap">
                    <Icon name="users" />
                    <input
                      type="number"
                      min={1}
                      max={50}
                      step={1}
                      inputMode="numeric"
                      placeholder="Number of travelers"
                      value={travelers}
                      onChange={(e) => setTravelers(e.target.value.replace(/[^0-9]/g, ""))}
                      onBlur={() => setTravelers(String(clampTravelers(travelers)))}
                    />
                  </div>
                </label>
                <label className="field">
                  <span>Stay preference</span>
                  <div className="input-wrap">
                    <Icon name="hotel" />
                    <select
                      value={stayPreference}
                      onChange={(e) => setStayPreference(e.target.value)}
                    >
                      <option>Boutique hotel</option>
                      <option>Luxury hotel</option>
                      <option>Budget stay</option>
                    </select>
                  </div>
                </label>
              </div>
            </div>
          )}

          {step === 3 && (
            <div>
              <label className="field">
                <span>What matters most?</span>
              </label>
              <div className="tag-options">
                {[
                  "Local culture",
                  "Great food",
                  "Nature",
                  "Slow pace",
                  "Hidden gems",
                  "Family friendly",
                  "Nightlife",
                  "Beaches",
                  "Work & Productivity",
                ].map((x) => {
                  const active = priorities.includes(x);
                  return (
                    <button
                      type="button"
                      className={active ? "selected" : ""}
                      onClick={() => togglePriority(x)}
                      key={x}
                    >
                      {x}
                      <Icon name={active ? "check" : "heart"} size={15} />
                    </button>
                  );
                })}
              </div>

              <label className="field spaced">
                <span>
                  Anything we should know? <em>Optional</em>
                </span>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Dietary needs, accessibility, must-see places, or anything else..."
                />
              </label>

              {/* Premium Feature: Budget Constraint Optimization */}
              <label className="premium-switch">
                <div>
                  <span className="icon-box yellow">
                    <Icon name="spark" />
                  </span>
                  <div>
                    <b>Optimize around my budget</b>
                    <small>Premium feature · Balance comfort and cost automatically</small>
                  </div>
                </div>
                <button
                  type="button"
                  className={premiumOptim ? "switch on" : "switch"}
                  onClick={() => setPremiumOptim(!premiumOptim)}
                >
                  <i />
                </button>
              </label>

              {premiumOptim && (
                <div className="budget-row">
                  <label className="field">
                    <span>Total travel budget</span>
                    <div className="input-wrap">
                      <b>{CURRENCIES.find((c) => c.code === currency)?.symbol}</b>
                      <input
                        value={budgetVal}
                        onChange={(e) => setBudgetVal(e.target.value)}
                        placeholder="e.g. 1500 or 4500"
                      />
                    </div>
                  </label>
                  <label className="field">
                    <span>Currency</span>
                    <div className="input-wrap">
                      <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                        {CURRENCIES.map((c) => (
                          <option key={c.code} value={c.code}>
                            {c.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </label>
                </div>
              )}
            </div>
          )}

          <div className="planner-footer">
            <span>
              {step === 1
                ? "Required fields are marked with *"
                : "Your travel preferences guide our AI Agent tools."}
            </span>
            <button
              className="btn btn-primary"
              disabled={isLoading}
              onClick={() => (step < 3 ? setStep(step + 1) : handleFinish())}
            >
              {isLoading ? (
                <span>AI Agent thinking...</span>
              ) : step < 3 ? (
                <>Continue <Icon name="arrow" size={17} /></>
              ) : (
                <>Create my travel plan <Icon name="spark" size={17} /></>
              )}
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}

// "2026-04-08", "2026-04-15" -> "Apr 8 – Apr 15, 2026"
function formatTripDates(start: string, end: string) {
  const parse = (s: string) => {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, (m || 1) - 1, d || 1);
  };
  const a = parse(start);
  const b = parse(end);
  if (isNaN(a.getTime()) || isNaN(b.getTime())) return `${start} – ${end}`;
  const md: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  const sameYear = a.getFullYear() === b.getFullYear();
  const left = a.toLocaleDateString("en-US", sameYear ? md : { ...md, year: "numeric" });
  const right = b.toLocaleDateString("en-US", { ...md, year: "numeric" });
  return `${left} – ${right}`;
}

function shortDay(dateStr: string) {
  const [y, m, d] = dateStr.split("-").map(Number);
  const date = new Date(y, (m || 1) - 1, d || 1);
  if (isNaN(date.getTime())) return dateStr;
  return date.toLocaleDateString("en-US", { weekday: "short", day: "numeric" });
}

const money = (n: number) => `$${Math.round(n).toLocaleString()}`;

const BUDGET_PARTS: { key: keyof BudgetBreakdown; label: string; color: string }[] = [
  // Shades of blue, darkest to lightest, spaced far apart so each one is easy to tell apart.
  { key: "accommodation", label: "Stays", color: "#001b6b" },
  { key: "food", label: "Food", color: "#0038de" },
  { key: "transportation", label: "Transport", color: "#3d7bff" },
  { key: "activities", label: "Activities", color: "#7fa8ff" },
  { key: "travel_essentials", label: "Essentials", color: "#b5ccff" },
  { key: "contingency_and_other", label: "Extras", color: "#dde7ff" },
];

function Results({
  plan,
  go,
  onAddToCart,
  userPlan,
  onSelectHotel,
  selectedHotel,
}: {
  plan: TripPlan;
  go: (v: View) => void;
  onAddToCart: (p: Product) => void;
  userPlan: "free" | "premium";
  onSelectHotel: (h: Hotel) => void;
  selectedHotel: Hotel | null;
}) {
  const [openDays, setOpenDays] = useState<number[]>([1]);
  const [showAgGrid, setShowAgGrid] = useState<boolean>(true);
  const [added, setAdded] = useState<string | null>(null);

  const activeHotel = selectedHotel || plan.recommended_hotel;
  const isPremium = plan.is_premium || userPlan === "premium";
  const budget = plan.budget_breakdown;
  const nights = plan.total_days;
  const allOpen = openDays.length === plan.itinerary.length;
  const isEgypt = /egypt|cairo|giza|luxor|aswan/i.test(plan.destination);

  const budgetParts = BUDGET_PARTS.map((p) => ({ ...p, value: Number(budget[p.key]) || 0 })).filter(
    (p) => p.value > 0
  );
  const partsTotal = budgetParts.reduce((s, p) => s + p.value, 0) || 1;
  const userBudget = budget.user_budget || null;
  const usedPct = userBudget ? Math.min(100, Math.round((budget.total_estimated / userBudget) * 100)) : null;
  const remaining = budget.remaining_balance ?? (userBudget ? userBudget - budget.total_estimated : null);
  const overBudget = remaining !== null && remaining < 0;
  // Must match GUESTS_PER_ROOM in the backend hotel service.
  const rooms = Math.max(1, Math.ceil(plan.travelers / 2));

  const toggleDay = (n: number) =>
    setOpenDays((prev) => (prev.includes(n) ? prev.filter((d) => d !== n) : [...prev, n]));

  const scrollTo = (id: string) =>
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

  const handleAdd = (p: Product) => {
    onAddToCart(p);
    setAdded(p.id);
    window.setTimeout(() => setAdded((cur) => (cur === p.id ? null : cur)), 1600);
  };

  return (
    <main className="app-bg explore">
      {/* ---------- Hero ---------- */}
      <section className="ex-hero page-shell">
        <img src={isEgypt ? editorHeroImage : heroImage} alt={plan.destination} />
        <div className="ex-hero-content">
          <span className="status-pill">
            <i /> YOUR PLAN IS READY · {isPremium ? "PREMIUM OPTIMIZED" : "FREE PLAN"}
          </span>
          <h1>{plan.destination}</h1>
          {plan.destination_summary && <p className="ex-hero-summary">{plan.destination_summary}</p>}
          <div className="ex-hero-chips">
            <span>
              <Icon name="calendar" size={16} /> {formatTripDates(plan.departure_date, plan.return_date)}
            </span>
            <span>
              <Icon name="clock" size={16} /> {nights} night{nights === 1 ? "" : "s"}
            </span>
            <span>
              <Icon name="users" size={16} /> {plan.travelers} traveler{plan.travelers > 1 ? "s" : ""}
            </span>
            <span>
              <Icon name="pin" size={16} /> {plan.purpose}
            </span>
          </div>
        </div>
        <div className="ex-hero-actions">
          <button className="btn btn-yellow" onClick={() => go("plan")}>
            Plan another trip <Icon name="arrow" size={16} />
          </button>
        </div>
      </section>

      {/* ---------- Section tabs ---------- */}
      <nav className="ex-tabs page-shell" aria-label="Plan sections">
        {[
          ["ex-overview", "Overview"],
          ["ex-stay", "Stay"],
          ["ex-itinerary", "Itinerary"],
          ["ex-essentials", "Essentials"],
        ].map(([id, label]) => (
          <button key={id} onClick={() => scrollTo(id)}>
            {label}
          </button>
        ))}
        <button className="ex-tabs-ai" onClick={() => go("assistant")}>
          <Icon name="spark" size={15} /> Ask MYMILE
        </button>
      </nav>

      <div className="page-shell ex-layout">
        <div className="ex-main">
          {/* ---------- Overview ---------- */}
          <section id="ex-overview" className="ex-section">
            <div className="ex-stats">
              <div className="ex-stat">
                <span className="icon-box blue">
                  <Icon name="cloud" />
                </span>
                <div>
                  <small>Weather now</small>
                  <b>{plan.weather.current_temp_c}°C</b>
                  <em>{plan.weather.current_condition}</em>
                </div>
              </div>
              <div className="ex-stat">
                <span className="icon-box yellow">
                  <Icon name="wallet" />
                </span>
                <div>
                  <small>Estimated cost</small>
                  <b>{money(budget.total_estimated)}</b>
                  <em className={overBudget ? "bad" : "good"}>
                    {overBudget ? "Over budget" : budget.status.replace(/_/g, " ")}
                  </em>
                </div>
              </div>
            </div>

            {plan.weather.forecast?.length > 0 && (
              <div className="ex-card ex-weather">
                <div className="ex-weather-head">
                  <div>
                    <span className="kicker">WEATHER FORECAST</span>
                    <small>{plan.weather.source}</small>
                  </div>
                </div>
                <div className="ex-forecast">
                  {plan.weather.forecast.slice(0, 7).map((f) => (
                    <div key={f.date}>
                      <small>{shortDay(f.date)}</small>
                      <b>{Math.round(f.temp_max_c)}°</b>
                      <span>{Math.round(f.temp_min_c)}°</span>
                      <em title={f.condition}>{f.condition}</em>
                    </div>
                  ))}
                </div>
                {plan.weather.packing_tip && (
                  <p className="ex-tip">
                    <Icon name="bag" size={17} />
                    <span>
                      <b>Packing tip:</b> {plan.weather.packing_tip}
                    </span>
                  </p>
                )}
              </div>
            )}
          </section>

          {/* ---------- Stay ---------- */}
          <section id="ex-stay" className="ex-section">
            <div className="ex-heading">
              <div>
                <span className="kicker">YOUR PERFECT STAY</span>
                <h2>
                  Handpicked <span>for you.</span>
                </h2>
              </div>
              {isPremium && plan.all_hotels.length > 1 && (
                <button className="ex-link" onClick={() => setShowAgGrid(!showAgGrid)}>
                  {showAgGrid ? "Hide comparison" : `Compare ${plan.all_hotels.length} stays`}{" "}
                  <Icon name="arrow" size={15} />
                </button>
              )}
            </div>

            <article className="ex-card ex-hotel">
              <div className="ex-hotel-img">
                <img src={activeHotel.image_url} alt={activeHotel.name} />
                <span className="ex-badge">
                  <Icon name="spark" size={13} /> BEST MATCH
                </span>
              </div>
              <div className="ex-hotel-body">
                <div className="ex-hotel-top">
                  <span className="ex-chip">{activeHotel.category}</span>
                  {activeHotel.rating > 0 && (
                    <span className="ex-rating">
                      <Icon name="star" size={15} /> {activeHotel.rating}
                      {activeHotel.reviews_count ? (
                        <small> ({activeHotel.reviews_count.toLocaleString()} reviews)</small>
                      ) : null}
                    </span>
                  )}
                </div>
                <h3>{activeHotel.name}</h3>
                <p className="ex-muted">
                  <Icon name="pin" size={15} /> {activeHotel.location}
                </p>
                <div className="ex-amenities">
                  {activeHotel.amenities.slice(0, 4).map((a) => (
                    <span key={a}>
                      <Icon name="check" size={13} /> {a}
                    </span>
                  ))}
                </div>
                <blockquote>“{activeHotel.best_match_reason}”</blockquote>
                <div className="ex-hotel-foot">
                  <div>
                    <small>
                      {activeHotel.price_source === "live" ? "" : "Est. "}
                      {money(activeHotel.price_per_night)} / room / night · {nights} night
                      {nights === 1 ? "" : "s"}
                      {rooms > 1 ? ` · ${rooms} rooms` : ""}
                    </small>
                    <b>{money(activeHotel.total_price)}</b>
                    {activeHotel.price_source === "live" ? (
                      <small className="ex-price-note live">
                        <Icon name="check" size={12} /> Live price for your dates
                        {activeHotel.price_provider ? ` from ${activeHotel.price_provider}` : ""}
                      </small>
                    ) : (
                      <small className="ex-price-note">
                        Estimate. The live price for your dates shows on Booking.com.
                      </small>
                    )}
                  </div>
                  {isPremium && activeHotel.booking_link ? (
                    <a
                      href={activeHotel.booking_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-primary"
                    >
                      See live price & book <Icon name="arrow" size={16} />
                    </a>
                  ) : !isPremium ? (
                    <button className="btn btn-secondary" onClick={() => go("pricing")}>
                      <Icon name="spark" size={15} /> Unlock booking link
                    </button>
                  ) : null}
                </div>
              </div>
            </article>

            {isPremium && showAgGrid && (
              <div className="ex-card ex-grid-card">
                <div className="ex-grid-head">
                  <span className="kicker">COMPARE STAYS</span>
                  <h3>Accommodation matrix</h3>
                  <p>Click any hotel to make it your stay. Your budget updates instantly.</p>
                </div>
                <AgGridHotelComparison
                  hotels={plan.all_hotels}
                  selectedHotelId={activeHotel.id}
                  onSelectHotel={onSelectHotel}
                  isPremium={isPremium}
                  totalNights={nights}
                />
                <div className="ex-grid-head second">
                  <span className="kicker">WHERE YOUR MONEY GOES</span>
                  <h3>Expense analytics</h3>
                  <p>Each category balanced by the MYMILE budget agent.</p>
                </div>
                <AgGridBudgetTable breakdown={budget} userBudget={budget.user_budget || undefined} />
              </div>
            )}
          </section>

          {/* ---------- Itinerary ---------- */}
          <section id="ex-itinerary" className="ex-section">
            <div className="ex-heading">
              <div>
                <span className="kicker">DAY BY DAY</span>
                <h2>
                  Your {plan.destination.split(",")[0]} <span>story.</span>
                </h2>
              </div>
              <div className="ex-heading-actions">
                <button
                  className="ex-link muted"
                  onClick={() => setOpenDays(allOpen ? [] : plan.itinerary.map((d) => d.day_number))}
                >
                  {allOpen ? "Collapse all" : "Expand all"}
                </button>
                <button className="ex-link" onClick={() => go("assistant")}>
                  Refine with AI <Icon name="spark" size={15} />
                </button>
              </div>
            </div>

            <div className="ex-days">
              {plan.itinerary.map((d) => {
                const isOpen = openDays.includes(d.day_number);
                return (
                  <article key={d.day_number} className={`ex-card ex-day${isOpen ? " open" : ""}`}>
                    <button
                      className="ex-day-head"
                      onClick={() => toggleDay(d.day_number)}
                      aria-expanded={isOpen}
                    >
                      <span className="ex-day-num">
                        <small>DAY</small>
                        <b>{String(d.day_number).padStart(2, "0")}</b>
                      </span>
                      <span className="ex-day-title">
                        <small>{d.date_str}</small>
                        <b>{d.theme}</b>
                      </span>
                      <span className="ex-day-count">
                        {d.activities.length} stop{d.activities.length === 1 ? "" : "s"}
                      </span>
                      <span className="ex-day-chevron">
                        <Icon name="chevron" size={18} />
                      </span>
                    </button>
                    {isOpen && (
                      <ol className="ex-timeline">
                        {d.activities.map((act, idx) => (
                          <li key={idx}>
                            <time>{act.time}</time>
                            <div>
                              <b>{act.title}</b>
                              <p>{act.description}</p>
                              {act.location && (
                                <span>
                                  <Icon name="pin" size={13} /> {act.location}
                                </span>
                              )}
                            </div>
                          </li>
                        ))}
                      </ol>
                    )}
                  </article>
                );
              })}
            </div>
          </section>

          {/* ---------- Essentials ---------- */}
          <section id="ex-essentials" className="ex-section">
            <div className="ex-heading">
              <div>
                <span className="kicker">PACK SMART</span>
                <h2>
                  Travel <span>essentials.</span>
                </h2>
              </div>
              <button className="ex-link" onClick={() => go("shop")}>
                View all {plan.travel_essentials.length} <Icon name="arrow" size={15} />
              </button>
            </div>
            <div className="ex-products">
              {plan.travel_essentials.slice(0, 3).map((prod) => (
                <article key={prod.id} className="ex-card ex-product">
                  <img src={prod.image_url} alt={prod.name} />
                  <div>
                    <span className="ex-product-cat">{prod.category}</span>
                    <h4>{prod.name}</h4>
                    <p>{prod.reason}</p>
                  </div>
                  <div className="ex-product-foot">
                    <b>${prod.price}</b>
                    <button
                      className={`btn btn-yellow btn-small${added === prod.id ? " done" : ""}`}
                      onClick={() => handleAdd(prod)}
                    >
                      {added === prod.id ? (
                        <>
                          <Icon name="check" size={15} /> Added
                        </>
                      ) : (
                        <>+ Add to cart</>
                      )}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>

        {/* ---------- Sidebar ---------- */}
        <aside className="ex-aside">
          <div className="ex-card ex-budget">
            <div className="ex-budget-head">
              <h3>Budget snapshot</h3>
              <span className={overBudget ? "bad" : "good"}>
                {overBudget ? "Over budget" : isPremium ? "Optimized" : "Estimate"}
              </span>
            </div>
            <div className="ex-budget-total">
              <small>Estimated total</small>
              <b>{money(budget.total_estimated)}</b>
              {userBudget && (
                <span>
                  of {money(userBudget)} budget · {usedPct}% used
                </span>
              )}
            </div>
            <div className="ex-stack" role="img" aria-label="Budget split by category">
              {budgetParts.map((p) => (
                <i
                  key={p.key}
                  style={{ width: `${(p.value / partsTotal) * 100}%`, background: p.color }}
                  title={`${p.label}: ${money(p.value)}`}
                />
              ))}
            </div>
            <ul className="ex-legend">
              {budgetParts.map((p) => (
                <li key={p.key}>
                  <span>
                    <i style={{ background: p.color }} /> {p.label}
                  </span>
                  <b>{money(p.value)}</b>
                </li>
              ))}
            </ul>
            {remaining !== null && (
              <div className={`ex-remaining${overBudget ? " bad" : ""}`}>
                <span>{overBudget ? "Over by" : "Remaining"}</span>
                <b>{money(Math.abs(remaining))}</b>
              </div>
            )}
            {!isPremium ? (
              <button className="ex-link" onClick={() => go("pricing")}>
                Unlock budget optimization <Icon name="arrow" size={15} />
              </button>
            ) : (
              <p className="ex-premium-note">
                <Icon name="check" size={15} /> Premium budget optimizer active
              </p>
            )}
          </div>

          <div className="ex-card ex-assistant">
            <span className="icon-box blue">
              <Icon name="spark" />
            </span>
            <h3>Your AI companion</h3>
            <p>Swap an activity, find a great local restaurant, or slow down the pace.</p>
            <button className="btn btn-primary full-btn" onClick={() => go("assistant")}>
              Ask MYMILE <Icon name="arrow" size={16} />
            </button>
          </div>

          <button className="ex-card ex-shop" onClick={() => go("shop")}>
            <span className="icon-box yellow">
              <Icon name="bag" />
            </span>
            <span>
              <b>Ready for {plan.destination.split(",")[0]}?</b>
              <small>{plan.travel_essentials.length} essentials picked for this trip</small>
            </span>
            <Icon name="chevron" size={18} />
          </button>
        </aside>
      </div>
    </main>
  );
}

function Assistant({
  trip,
  userPlan,
}: {
  trip: TripPlan | null;
  userPlan: 'free' | 'premium';
}) {
  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant'; text: string }>>([
    {
      role: 'assistant',
      text: trip
        ? `I’ve shaped your ${trip.destination} plan around ${trip.purpose.toLowerCase()}, comfortable boutique stays, and real-time weather (${trip.weather.current_condition}, ${trip.weather.current_temp_c}°C). What would you like to fine-tune?`
        : `Welcome to MYMILE! Tell me where you’d like to go or what adjustments you want to make.`
    }
  ]);
  const [text, setText] = useState("");
  const [isThinking, setIsThinking] = useState(false);

  const send = async (value = text) => {
    if (!value.trim()) return;
    const userMsg = value.trim();
    setMessages((prev) => [...prev, { role: 'user', text: userMsg }]);
    setText("");
    setIsThinking(true);

    try {
      const res = await api.chatWithCompanion({
        message: userMsg,
        current_trip_context: trip ? {
          destination: trip.destination,
          dates: `${trip.departure_date} to ${trip.return_date}`,
          budget: trip.budget_breakdown.total_estimated,
          weather: trip.weather.current_condition
        } : undefined,
        plan: userPlan,
        budget: trip?.budget_breakdown.total_estimated
      });

      setMessages((prev) => [...prev, { role: 'assistant', text: res.reply }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: `I've noted that! I’ll adjust your daily itinerary pace and coordinate with your verified boutique stay.`
        }
      ]);
    } finally {
      setIsThinking(false);
    }
  };

  return (
    <main className="app-bg assistant-page">
      <div className="chat-shell">
        <div className="chat-head">
          <div>
            <span className="icon-box blue">
              <Icon name="spark" />
            </span>
            <div>
              <h2>MYMILE Travel Companion</h2>
              <p>
                <i /> Online · {trip ? trip.destination : "Kyoto trip"} ({userPlan.toUpperCase()})
              </p>
            </div>
          </div>
          <span className="text-xs bg-blue-100 text-blue-800 font-bold px-2.5 py-1 rounded-full">
            AI Agent Active
          </span>
        </div>

        <div className="chat-body">
          {messages.map((m, i) => (
            <div key={i} className={m.role === 'assistant' ? "ai-message" : "user-message"}>
              {m.role === 'assistant' && (
                <span className="icon-box blue">
                  <Icon name="spark" size={18} />
                </span>
              )}
              <div>
                <p>{m.text}</p>
              </div>
            </div>
          ))}

          {isThinking && (
            <div className="ai-message">
              <span className="icon-box blue">
                <Icon name="spark" size={18} />
              </span>
              <div>
                <span className="thinking">
                  <i />
                  <i />
                  <i /> AI Agent consulting weather, hotels & Channel3 tools...
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="suggestions">
          {[
            "Find a special dinner",
            "Make day 3 slower",
            "What should I pack?",
            "How does budget look?"
          ].map((x) => (
            <button onClick={() => send(x)} key={x}>
              {x}
            </button>
          ))}
        </div>

        <div className="chat-input">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Ask anything about your itinerary, hotels, or packing..."
          />
          <button onClick={() => send()} aria-label="Send">
            <Icon name="send" />
          </button>
        </div>
      </div>
    </main>
  );
}

function Shop({
  products,
  onAddToCart,
  cartCount,
  onOpenCart,
}: {
  products: Product[];
  onAddToCart: (p: Product) => void;
  cartCount: number;
  onOpenCart: () => void;
}) {
  return (
    <main className="app-bg simple-page wide">
      <div className="page-intro left">
        <div className="flex items-center gap-2 mb-2">
          <span className="kicker">SPONSOR INTEGRATION · CHANNEL3</span>
          <span className="bg-yellow-400 text-gray-900 text-[10px] font-extrabold px-2 py-0.5 rounded">
            AUTHENTIC COMMERCE
          </span>
        </div>
        <h1>Destination Travel Essentials.</h1>
        <p>
          Real products, verified prices, and original purchase links powered by Channel3 AI Product Discovery.
        </p>
      </div>

      <div className="shop-toolbar flex items-center justify-between p-4 bg-white rounded-2xl border border-slate-200 mb-6 shadow-sm">
        <span className="text-xs font-bold text-gray-700">{products.length} essentials picked for your journey</span>
        <button
          onClick={onOpenCart}
          className="btn btn-primary btn-small flex items-center gap-2"
        >
          <Icon name="bag" size={17} /> View Cart ({cartCount})
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {products.map((prod) => (
          <article className="product-card flex flex-col justify-between h-full bg-white rounded-2xl border border-slate-200 shadow-sm p-4 hover:shadow-md transition-shadow" key={prod.id}>
            <div>
              <img src={prod.image_url} alt={prod.name} className="w-full h-48 object-cover rounded-xl mb-4" />
              <div className="flex items-center justify-between gap-2 mb-1">
                <small className="text-[10px] font-bold text-blue-600 uppercase tracking-wider">{prod.category}</small>
                <span className="text-xs text-yellow-500 font-bold">★ {prod.rating}</span>
              </div>
              <h3 className="text-base font-bold text-gray-900 leading-snug">{prod.name}</h3>
              <p className="text-xs text-gray-600 mt-2 leading-relaxed">{prod.description}</p>
              <div className="p-2.5 bg-slate-50 rounded-lg border border-slate-100 mt-3 text-[11px] text-gray-600 italic">
                “{prod.reason}”
              </div>
            </div>

            <div className="pt-4 mt-4 border-t border-slate-100">
              <div className="flex items-center justify-between mb-3">
                <b className="text-lg font-black text-gray-900">${prod.price.toFixed(2)}</b>
                <button
                  onClick={() => onAddToCart(prod)}
                  className="btn btn-yellow btn-small"
                >
                  Add to cart
                </button>
              </div>
              <div className="flex items-center justify-between text-[11px] text-gray-400">
                <span>{prod.provider}</span>
                <a
                  href={prod.purchase_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 font-semibold hover:underline"
                >
                  View on partner site ↗
                </a>
              </div>
            </div>
          </article>
        ))}
      </div>
    </main>
  );
}

function Pricing({
  userPlan,
  onSelectPlan,
  go
}: {
  userPlan: 'free' | 'premium';
  onSelectPlan: (p: 'free' | 'premium') => void;
  go: (v: View) => void;
}) {
  return (
    <main className="app-bg simple-page">
      <div className="page-intro">
        <span className="kicker">SIMPLE, HONEST PRICING</span>
        <h1>Travel smarter at every mile.</h1>
        <p>Start with basic AI travel planning. Upgrade to Premium for custom budget constraints and AG Grid analytics.</p>
      </div>

      <div className="plans">
        <article className={`price-card ${userPlan === 'free' ? 'border-2 border-blue-600 ring-2 ring-blue-100' : ''}`}>
          <div className="flex items-center justify-between">
            <span className="plan-label">FREE PLAN</span>
            {userPlan === 'free' && (
              <span className="text-[11px] bg-green-100 text-green-800 font-bold px-2 py-0.5 rounded-full">ACTIVE</span>
            )}
          </div>
          <h2>
            $0 <small>forever</small>
          </h2>
          <p>For curious travelers ready to turn ideas into a clear plan.</p>
          <button
            className="btn btn-secondary full-btn"
            onClick={() => {
              onSelectPlan('free');
              alert("Activated Free Plan");
            }}
          >
            {userPlan === 'free' ? 'Current Plan' : 'Switch to Free'}
          </button>
          {[
            "AI travel planning",
            "Hotel recommendations & estimates",
            "Live meteorological weather insights",
            "Channel3 travel essentials discovery",
            "Basic daily itinerary",
            "Estimated baseline trip costs",
          ].map((x) => (
            <div className="plan-feature" key={x}>
              <Icon name="check" size={17} />
              {x}
            </div>
          ))}
          <div className="pt-4 border-t border-slate-100 text-xs text-gray-400">
            * Direct hotel booking links and AG Grid comparison tables gated for Premium.
          </div>
        </article>

        <article className={`price-card premium ${userPlan === 'premium' ? 'ring-4 ring-yellow-300' : ''}`}>
          <div className="popular">MOST LOVED</div>
          <div className="flex items-center justify-between">
            <span className="plan-label">
              <span className="premium-spark">
                <Icon name="spark" size={14} />
              </span>{" "}
              PREMIUM PLAN
            </span>
            {userPlan === 'premium' && (
              <span className="text-[11px] bg-yellow-400 text-gray-950 font-black px-2 py-0.5 rounded-full">ACTIVE</span>
            )}
          </div>
          <h2>
            $100<small>/month</small>
          </h2>
          <p>For travelers who want the best experience balanced within a real budget.</p>
          <button
            className="btn btn-yellow full-btn"
            onClick={() => {
              onSelectPlan('premium');
              alert("Premium Plan Activated! AG Grid and Budget Optimization unlocked.");
            }}
          >
            {userPlan === 'premium' ? 'Current Plan' : 'Upgrade to Premium'}
          </button>
          {[
            "Everything in Free Plan",
            "Smart budget optimization (e.g. $1,500 budget)",
            "Interactive AG Grid hotel comparison matrix",
            "Interactive AG Grid budget breakdown table",
            "Dynamic recalculation when swapping hotels",
            "Priority AI companion guidance",
          ].map((x) => (
            <div className="plan-feature" key={x}>
              <Icon name="check" size={17} />
              {x}
            </div>
          ))}
        </article>
      </div>
    </main>
  );
}

function Trips({ go }: { go: (v: View) => void }) {
  return (
    <main className="app-bg simple-page wide">
      <div className="page-intro left">
        <span className="kicker">YOUR JOURNEYS</span>
        <h1>Trips worth looking forward to.</h1>
        <p>Pick up where you left off or start imagining somewhere new.</p>
      </div>
      <div className="trip-list">
        <article className="saved-trip cursor-pointer" onClick={() => go("results")}>
          <img src={heroImage} alt="Kyoto" />
          <div>
            <span className="status-pill">
              <i /> UPCOMING · 98% MATCH
            </span>
            <h2>Kyoto in bloom</h2>
            <p>Apr 8–15, 2026 · 2 travelers · Tourism</p>
            <div className="trip-meta">
              <span>
                <Icon name="calendar" size={16} /> 7 days
              </span>
              <span>
                <Icon name="spark" size={16} /> Granbell Hotel
              </span>
            </div>
          </div>
          <button onClick={() => go("results")}>
            <Icon name="arrow" />
          </button>
        </article>

        <button className="new-trip" onClick={() => go("plan")}>
          <span>+</span>
          <b>Plan a new adventure</b>
          <p>Where will your next mile take you?</p>
        </button>
      </div>
    </main>
  );
}

function Profile({
  user,
  onTogglePlan,
  go
}: {
  user: User;
  onTogglePlan: () => void;
  go: (v: View) => void;
}) {
  return (
    <main className="app-bg simple-page wide">
      <div className="profile-layout">
        <aside>
          <div className="profile-avatar">{getInitials(user.name)}</div>
          <h2>{user.name}</h2>
          <p>{user.email}</p>
          <button
            onClick={onTogglePlan}
            className={`premium-pill mt-2 font-bold cursor-pointer ${
              user.plan === 'premium' ? 'bg-yellow-400 text-gray-900' : 'bg-gray-200 text-gray-700'
            }`}
          >
            <Icon name="spark" size={13} /> {user.plan.toUpperCase()}
          </button>
          <nav className="mt-4">
            <button className="active">Personal Profile</button>
            <button onClick={() => go("trips")}>Saved Trips</button>
            <button onClick={() => go("pricing")}>Subscription Plans</button>
          </nav>
        </aside>

        <section className="profile-content">
          <span className="kicker">YOUR ACCOUNT</span>
          <h1>Personal details</h1>
          <p>Keep your details current so every journey feels personal.</p>
          <div className="form-grid">
            <label className="field">
              <span>First name</span>
              <div className="input-wrap">
                <input defaultValue={user.name.split(" ")[0]} />
              </div>
            </label>
            <label className="field">
              <span>Last name</span>
              <div className="input-wrap">
                <input defaultValue={user.name.split(" ")[1] || ""} />
              </div>
            </label>
            <label className="field full">
              <span>Email address</span>
              <div className="input-wrap">
                <input defaultValue={user.email} />
              </div>
            </label>
          </div>
          <button className="btn btn-primary" onClick={() => alert("Profile updated!")}>
            Save changes
          </button>
        </section>
      </div>
    </main>
  );
}

function AuthPhoto({ image, alt }: { image: string; alt: string }) {
  return (
    <div className="login-photo">
      <img src={image} alt={alt} />
      <div>
        <span className="kicker">YOUR SMILE, EVERY MILE.</span>
        <h2>
          The world is waiting.
          <br />
          Let’s plan beautifully.
        </h2>
      </div>
    </div>
  );
}

function Login({ go, onAuth }: { go: (v: View) => void; onAuth: (u: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const data = await api.login(email.trim(), password, remember);
      onAuth(data.user);
    } catch (err) {
      setError(getErrorMessage(err));
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <AuthPhoto image={editorLoginImage} alt="The Colosseum in Rome at dusk" />
      <div className="login-form">
        <form onSubmit={handleSubmit} noValidate={false}>
          <span className="kicker">WELCOME BACK</span>
          <h1>Continue your journey.</h1>
          <p>Sign in to access your saved trips and AG Grid dashboards.</p>
          {error && (
            <div className="auth-error" role="alert">
              {error}
            </div>
          )}
          <label className="field">
            <span>Email address</span>
            <div className="input-wrap">
              <input
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </label>
          <label className="field">
            <span>Password</span>
            <div className="input-wrap">
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </label>
          <div className="login-options">
            <label>
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
              />{" "}
              Remember me
            </label>
            <button type="button">Forgot password?</button>
          </div>
          <button type="submit" className="btn btn-primary full-btn" disabled={submitting}>
            {submitting ? "Logging in…" : <>Log in <Icon name="arrow" size={17} /></>}
          </button>
          <p className="signup-note">
            Don’t have an account?{" "}
            <button type="button" onClick={() => go("signup")}>
              Sign up
            </button>
          </p>
        </form>
      </div>
    </main>
  );
}

function Signup({ go, onAuth }: { go: (v: View) => void; onAuth: (u: User) => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const mismatch = confirm.length > 0 && password !== confirm;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirm) return;
    setError("");
    setSubmitting(true);
    try {
      const data = await api.register(name.trim(), email.trim(), password);
      onAuth(data.user);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <AuthPhoto image={signupImage} alt="The Colosseum seen from a balcony at night" />
      <div className="login-form">
        <form onSubmit={handleSubmit}>
          <span className="kicker">JOIN MYMILE</span>
          <h1>Start your journey.</h1>
          <p>Create an account to save your trips and plan every mile in one place.</p>
          {error && (
            <div className="auth-error" role="alert">
              {error}
            </div>
          )}
          <label className="field">
            <span>Full name</span>
            <div className="input-wrap">
              <input
                type="text"
                autoComplete="name"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
          </label>
          <label className="field">
            <span>Email address</span>
            <div className="input-wrap">
              <input
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </label>
          <div className="auth-row">
            <label className="field">
              <span>Password</span>
              <div className="input-wrap">
                <input
                  type="password"
                  autoComplete="new-password"
                  minLength={8}
                  required
                  placeholder="At least 8 characters"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
            </label>
            <label className="field">
              <span>Confirm password</span>
              <div className="input-wrap">
                <input
                  type="password"
                  autoComplete="new-password"
                  required
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                />
              </div>
            </label>
          </div>
          {mismatch && <small className="field-error">Passwords don’t match.</small>}
          <div className="login-options">
            <label>
              <input type="checkbox" required /> I agree to the Terms and Privacy Policy
            </label>
          </div>
          <button type="submit" className="btn btn-primary full-btn" disabled={submitting || mismatch}>
            {submitting ? "Creating account…" : <>Sign up <Icon name="arrow" size={17} /></>}
          </button>
          <p className="signup-note">
            Already have an account?{" "}
            <button type="button" onClick={() => go("login")}>
              Log in
            </button>
          </p>
        </form>
      </div>
    </main>
  );
}

function Footer({ go, onOpenApimatic }: { go: (v: View) => void; onOpenApimatic: () => void }) {
  return (
    <footer>
      <div className="page-shell footer-grid">
        <div>
          <img src={logo} alt="MYMILE" className="h-8 w-auto mb-3" />
          <p>Your intelligent travel companion for happier journeys, every mile.</p>
          <div className="mt-3 text-xs text-slate-400">
            Powered by Channel3 AI Commerce, AG Grid, Open-Meteo & APIMatic
          </div>
        </div>
        <div>
          <b>Explore</b>
          <button onClick={() => go("plan")}>Plan a trip</button>
          <button onClick={() => go("results")}>Dashboard</button>
          <button onClick={() => go("pricing")}>Pricing Plans</button>
          <button onClick={() => go("shop")}>Travel Gear</button>
        </div>
        <div>
          <b>Developers</b>
          <button onClick={onOpenApimatic}>APIMatic SDKs</button>
          <a href="/docs" target="_blank" rel="noreferrer" className="block text-slate-400 text-sm hover:text-white py-1">
            FastAPI Docs ↗
          </a>
          <a href="/api/apimatic/openapi.json" target="_blank" rel="noreferrer" className="block text-slate-400 text-sm hover:text-white py-1">
            OpenAPI Spec ↗
          </a>
        </div>
      </div>
      <div className="page-shell copyright">
        <span>© 2026 MYMILE. Your smile, with you every mile.</span>
        <span>Channel3 · AG Grid · APIMatic · Google Gemini</span>
      </div>
    </footer>
  );
}

// Guest experience shown when nobody is logged in.
const DEMO_USER: User = {
  id: "usr-alex",
  name: "Alex Morgan",
  email: "alex@example.com",
  plan: "premium",
  created_at: "2026-01-15T10:00:00Z",
};

export default function App() {
  const [view, setView] = useState<View>("home");
  const [isLoading, setIsLoading] = useState(false);
  // The logged-in account (null = guest). Restored from a saved session on load.
  const [authUser, setAuthUser] = useState<User | null>(() => getStoredUser<User>());
  const [user, setUser] = useState<User>(() => getStoredUser<User>() ?? DEMO_USER);

  // Confirm a saved session is still valid with the server.
  useEffect(() => {
    if (!getStoredToken()) return;
    api
      .getMe()
      .then((me: User) => {
        setAuthUser(me);
        setUser(me);
      })
      .catch((err) => {
        // Only drop the session if the server rejected it, not if it's just unreachable.
        if (err?.response?.status === 401) {
          api.logout();
          setAuthUser(null);
          setUser(DEMO_USER);
        }
      });
  }, []);

  const [currentTrip, setCurrentTrip] = useState<TripPlan | null>(null);
  const [selectedHotel, setSelectedHotel] = useState<Hotel | null>(null);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [isCartOpen, setIsCartOpen] = useState(false);
  const [isApimaticOpen, setIsApimaticOpen] = useState(false);

  // Initialize with a default rich plan on first load
  useEffect(() => {
    async function loadInitialPlan() {
      try {
        const plan = await api.planTrip({
          destination: "Kyoto, Japan",
          departure_date: "2026-04-08",
          return_date: "2026-04-15",
          travelers: 2,
          purpose: "Tourism",
          stay_preference: "Boutique hotel",
          priorities: ["Local culture", "Great food", "Slow pace"],
          plan: user.plan,
          total_budget: user.plan === "premium" ? 4500 : undefined,
        });
        setCurrentTrip(plan);
        setSelectedHotel(plan.recommended_hotel);
      } catch (err) {
        console.error("Initial load failed, will generate on demand:", err);
      }
    }
    loadInitialPlan();
  }, []);

  const handleTogglePlan = async () => {
    const nextPlan = user.plan === "premium" ? "free" : "premium";
    setUser((prev) => ({ ...prev, plan: nextPlan }));
    if (currentTrip) {
      // Re-run planning with the new plan tier
      setIsLoading(true);
      try {
        const updated = await api.planTrip({
          destination: currentTrip.destination,
          departure_date: currentTrip.departure_date,
          return_date: currentTrip.return_date,
          travelers: currentTrip.travelers,
          purpose: currentTrip.purpose,
          stay_preference: currentTrip.stay_preference,
          plan: nextPlan,
          total_budget: nextPlan === "premium" ? 4500 : undefined,
        });
        setCurrentTrip(updated);
        setSelectedHotel(updated.recommended_hotel);
      } catch (err) {
        console.error("Error refreshing plan:", err);
      } finally {
        setIsLoading(false);
      }
    }
  };

  const handleGeneratePlan = async (data: any) => {
    setIsLoading(true);
    try {
      const plan = await api.planTrip(data);
      setCurrentTrip(plan);
      setSelectedHotel(plan.recommended_hotel);
    } catch (err) {
      alert("Failed to generate plan. Please verify backend is running on http://127.0.0.1:8000.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectHotel = (hotel: Hotel) => {
    setSelectedHotel(hotel);
    if (currentTrip && user.plan === "premium") {
      // Recalculate remaining budget with newly selected hotel
      const userBudget = currentTrip.budget_breakdown.user_budget || 4500;
      const hotelCost = hotel.total_price;
      const otherCosts = currentTrip.budget_breakdown.food +
        currentTrip.budget_breakdown.transportation +
        currentTrip.budget_breakdown.activities +
        currentTrip.budget_breakdown.travel_essentials +
        currentTrip.budget_breakdown.contingency_and_other;
      const newTotal = hotelCost + otherCosts;
      const newRemaining = userBudget - newTotal;

      setCurrentTrip({
        ...currentTrip,
        recommended_hotel: hotel,
        budget_breakdown: {
          ...currentTrip.budget_breakdown,
          accommodation: hotelCost,
          total_estimated: newTotal,
          remaining_balance: newRemaining,
          status: newRemaining >= 0 ? "balanced" : "over_budget",
        }
      });
    }
  };

  const handleAddToCart = (product: Product) => {
    setCart((prev) => {
      const existing = prev.find((item) => item.product.id === product.id);
      if (existing) {
        return prev.map((item) =>
          item.product.id === product.id
            ? { ...item, quantity: item.quantity + 1 }
            : item
        );
      }
      return [...prev, { product, quantity: 1 }];
    });
    setIsCartOpen(true);
  };

  const handleUpdateCartQuantity = (productId: string, delta: number) => {
    setCart((prev) =>
      prev
        .map((item) => {
          if (item.product.id === productId) {
            const newQ = item.quantity + delta;
            return newQ > 0 ? { ...item, quantity: newQ } : null;
          }
          return item;
        })
        .filter(Boolean) as CartItem[]
    );
  };

  const handleRemoveCartItem = (productId: string) => {
    setCart((prev) => prev.filter((item) => item.product.id !== productId));
  };

  const go = (v: View) => {
    setView(v);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleAuth = (u: User) => {
    setAuthUser(u);
    setUser(u);
    go("home");
  };

  const handleLogout = () => {
    api.logout();
    setAuthUser(null);
    setUser(DEMO_USER);
    go("home");
  };

  const totalCartCount = cart.reduce((acc, i) => acc + i.quantity, 0);

  const content = useMemo(() => {
    if (view === "home") return <Home go={go} onOpenApimatic={() => setIsApimaticOpen(true)} />;
    if (view === "plan") return (
      <Planner
        go={go}
        onGeneratePlan={handleGeneratePlan}
        isLoading={isLoading}
        userPlan={user.plan}
      />
    );
    if (view === "results") {
      if (!currentTrip) {
        return (
          <div className="min-h-[500px] flex items-center justify-center text-center p-8">
            <div>
              <h2 className="text-xl font-bold">No active travel plan yet</h2>
              <p className="text-gray-500 mt-2">Let our AI agent build your dream journey.</p>
              <button className="btn btn-primary mt-4" onClick={() => go("plan")}>
                Start Planning
              </button>
            </div>
          </div>
        );
      }
      return (
        <Results
          plan={currentTrip}
          go={go}
          onAddToCart={handleAddToCart}
          userPlan={user.plan}
          onSelectHotel={handleSelectHotel}
          selectedHotel={selectedHotel}
        />
      );
    }
    if (view === "pricing") return (
      <Pricing
        userPlan={user.plan}
        onSelectPlan={(p) => setUser((u) => ({ ...u, plan: p }))}
        go={go}
      />
    );
    if (view === "assistant") return <Assistant trip={currentTrip} userPlan={user.plan} />;
    if (view === "trips") return <Trips go={go} />;
    if (view === "shop") return (
      <Shop
        products={currentTrip ? currentTrip.travel_essentials : []}
        onAddToCart={handleAddToCart}
        cartCount={totalCartCount}
        onOpenCart={() => setIsCartOpen(true)}
      />
    );
    if (view === "profile") return <Profile user={user} onTogglePlan={handleTogglePlan} go={go} />;
    if (view === "signup") return <Signup go={go} onAuth={handleAuth} />;
    return <Login go={go} onAuth={handleAuth} />;
  }, [view, currentTrip, selectedHotel, user, isLoading, cart]);

  return (
    <>
      <Header
        view={view}
        setView={go}
        authUser={authUser}
        onLogout={handleLogout}
      />
      {content}
      {!["plan", "assistant", "login", "signup"].includes(view) && (
        <Footer go={go} onOpenApimatic={() => setIsApimaticOpen(true)} />
      )}

      {/* Slide-over Shopping Cart */}
      <ShoppingCartDrawer
        isOpen={isCartOpen}
        onClose={() => setIsCartOpen(false)}
        items={cart}
        onUpdateQuantity={handleUpdateCartQuantity}
        onRemoveItem={handleRemoveCartItem}
      />

      {/* APIMatic SDK & OpenAPI Modal */}
      <ApimaticModal
        isOpen={isApimaticOpen}
        onClose={() => setIsApimaticOpen(false)}
      />
    </>
  );
}
