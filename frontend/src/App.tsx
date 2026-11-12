import { useMemo, useState, useEffect, useRef, useCallback } from "react";
import logo from "./assets/mymile-logo.png";
import egyptTravelImage from "./imports/20__Europe_Travel_Bucket_List_Tips_You_Need_for_an_Unforgettable_Adventure.jpg";
import editorHeroImage from "./imports/editor-hero-egypt.jpg";
import editorLoginImage from "./imports/editor-login-egypt.jpg";
import signupImage from "./imports/download__2_.jpg";
import { AgGridHotelComparison } from "./components/AgGridHotelComparison";
import { AgGridBudgetTable } from "./components/AgGridBudgetTable";
import { PremiumCheckout } from "./components/PremiumCheckout";
import { SessionExpiredError } from "./services/payments";
import { api, getStoredToken, getStoredUser, getErrorMessage, updateStoredUser } from "./services/api";
import { TripPlan, Hotel, HotelOffers, Product, User, BudgetBreakdown, PremiumTerms, DestinationImage } from "./types";
import {
  TripRequest,
  DESCRIPTION_MAX,
  cleanDescription,
  descriptionError,
  StoredTrips,
  accountKey,
  browserStore,
  getActiveTrip,
  loadTrips,
  newTripId,
  saveTrip,
  setActiveTrip,
  toPlanPayload,
} from "./services/tripStore";
import {
  bookingView,
  canShowBudget,
  formatMoney,
  heroLocation,
  isLiveHotel,
  isPremiumView,
  mergeOffers,
  needsOffers,
  offersRequest,
  otherOffers,
  PRICE_VARIES_NOTE,
  bookingPriceLine,
  priceDisclaimer,
  priceMeta,
  priceView,
  showsEstimateLabel,
} from "./services/exploreView";

// Subtle "Estimated" tag shown next to hotel prices; the tooltip explains why.
function EstimatedLabel() {
  return (
    <span className="price-est" title={PRICE_VARIES_NOTE}>
      Estimated
    </span>
  );
}
import { BudgetImpact, applyHotelSelection } from "./services/hotelComparison";
import { budgetView } from "./services/budgetView";
import {
  audienceLabel,
  availabilityLabel,
  essentialsEmptyMessage,
  manualSearchQuery,
  missingCategoriesNote,
  productPrice,
  productSource,
  viewProductUrl,
} from "./services/productView";
import {
  DEFAULT_SUGGESTIONS,
  aiPlanLabel,
  aiProviderName,
  buildChatContext,
  recentHistory,
  suggestedHotel,
  toolList,
} from "./services/assistantChat";

// Trip fields entered in Plan a Trip (id/created_at are added when saved).
type TripInput = Omit<TripRequest, "id" | "created_at">;

// "$9" for 9.00 USD, "$9.50" for 9.50 USD, "€9" for EUR... (display only).
function formatPremiumPrice(terms: PremiumTerms | null): string {
  if (!terms) return "…";
  const value = Number(terms.price);
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: terms.currency,
      minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${terms.price} ${terms.currency}`;
  }
}

function formatExpiry(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

type View =
  | "home"
  | "plan"
  | "results"
  | "trips"
  | "pricing"
  | "profile"
  | "login"
  | "signup"
  | "assistant";

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
  ["cloud", "Weather-wise plans", "Daily forecasts shape your stay and packing list."],
  ["bag", "Travel essentials", "Smart product picks via Channel3 for your destination & season."],
  ["wallet", "Budget optimization", "See where every dollar goes and make confident trade-offs."],
  ["route", "One connected journey", "Interactive AG Grid dashboards to compare stays and budgets."],
] as [IconName, string, string][];

function Home({
  go,
  premiumTerms,
}: {
  go: (v: View) => void;
  premiumTerms: PremiumTerms | null;
}) {
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
              Tell us how you want to travel. MYMILE finds the right stays, picks your travel essentials, checks the weather, and helps every mile fit your budget.
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
          <span>Integrated with Channel3 & AG Grid</span>
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
                  "Travel with a plan and companion that are always there when you need them.",
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
                {formatPremiumPrice(premiumTerms)}
                <small>{premiumTerms ? ` / ${premiumTerms.duration_days} days · one-time` : ""}</small>
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
  onGeneratePlan: (data: TripInput) => Promise<boolean>;
  isLoading: boolean;
  userPlan: 'free' | 'premium';
}) {
  const [step, setStep] = useState(1);
  // City and Country are separate, required fields: they are the authoritative
  // location for hotels and weather.
  const [city, setCity] = useState("");
  const [country, setCountry] = useState("");
  const step1Missing = !city.trim() || !country.trim();
  const [departureDate, setDepartureDate] = useState(() => toDateInputValue(new Date()));
  const [returnDate, setReturnDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 5);
    return toDateInputValue(d);
  });
  const [purpose, setPurpose] = useState("Tourism");
  const [travelers, setTravelers] = useState("2");
  const [stayPreference, setStayPreference] = useState("Boutique hotel");
  const [notes, setNotes] = useState("");
  const notesError = descriptionError(notes);
  const [notesTouched, setNotesTouched] = useState(false); // show the error after leaving the field
  // "Who are you shopping for?" — optional; a shopping preference, not the traveler's identity.
  const [shoppingAudience, setShoppingAudience] = useState<"all" | "men" | "women">("all");
  // Budget optimization is a Premium feature. For Free accounts it is always off
  // (whatever was chosen before), and clicking it opens the Pricing page instead.
  const isPremiumUser = userPlan === "premium";
  const [premiumChoice, setPremiumOptim] = useState(true);
  const premiumOptim = isPremiumUser && premiumChoice;
  const handleOptimToggle = () => {
    if (!isPremiumUser) {
      go("pricing");
      return;
    }
    setPremiumOptim(!premiumOptim);
  };
  const [budgetVal, setBudgetVal] = useState("4500");

  const titles = ["Where are you headed?", "Who’s coming along?", "Make it feel like you"];


  const handleFinish = async () => {
    if (descriptionError(notes)) return; // required; the button is disabled too
    const c = city.trim();
    const k = country.trim();
    await onGeneratePlan({
      destination: `${c}, ${k}`,
      destination_city: c,
      destination_country: k,
      departure_date: departureDate,
      return_date: returnDate,
      travelers: clampTravelers(travelers),
      purpose,
      stay_preference: stayPreference,
      priorities: [], // "What matters most?" was removed; the trip description carries preferences
      notes: cleanDescription(notes), // the trip description; never used as the destination
      shopping_audience: shoppingAudience,
      total_budget: premiumOptim ? parseFloat(budgetVal.replace(/,/g, "")) || 4500 : undefined,
    });
    go("results"); // Explore shows loading / error / the new trip
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
              <label className="field">
                <span>
                  Destination city <b>*</b>
                </span>
                <div className="input-wrap">
                  <Icon name="pin" />
                  <input
                    value={city}
                    onChange={(e) => setCity(e.target.value)}
                    placeholder="e.g. Cairo"
                    autoComplete="address-level2"
                    required
                  />
                </div>
              </label>
              <label className="field">
                <span>
                  Country <b>*</b>
                </span>
                <div className="input-wrap">
                  <Icon name="pin" />
                  <input
                    value={country}
                    onChange={(e) => setCountry(e.target.value)}
                    placeholder="e.g. Egypt"
                    autoComplete="country-name"
                    required
                  />
                </div>
              </label>
              <small className="field full planner-hint">
                Try: Cairo, Egypt · Alexandria, Egypt · Kyoto, Japan · Paris, France · Makkah, Saudi Arabia
              </small>
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
                <span>
                  Tell us about your trip <em className="required">*</em>
                </span>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value.slice(0, DESCRIPTION_MAX))}
                  maxLength={DESCRIPTION_MAX}
                  required
                  aria-required="true"
                  aria-describedby="trip-description-help"
                  onBlur={() => setNotesTouched(true)}
                  placeholder="e.g. A summer beach vacation with some city exploration, or a business trip with an important conference..."
                />
                <small id="trip-description-help" className={`char-count${notesTouched && notesError ? " bad" : ""}`}>
                  {notesTouched && notesError ? notesError : "We use this to pick the right travel products."}
                  <span>{notes.length}/{DESCRIPTION_MAX}</span>
                </small>
              </label>

              {/* Shopping preferences: only used to pick travel products. */}
              <fieldset className="shopping-prefs">
                <legend>Shopping preferences</legend>
                <label className="field">
                  <span>
                    Who are you shopping for? <em>Optional</em>
                  </span>
                  <div className="input-wrap">
                    <Icon name="bag" />
                    <select value={shoppingAudience} onChange={(e) => setShoppingAudience(e.target.value as "all" | "men" | "women")}>
                      <option value="all">Everyone / No preference</option>
                      <option value="men">Men</option>
                      <option value="women">Women</option>
                    </select>
                  </div>
                </label>
              </fieldset>

              {/* Premium Feature: Budget Constraint Optimization */}
              <label className="premium-switch">
                <div>
                  <span className="icon-box yellow">
                    <Icon name="spark" />
                  </span>
                  <div>
                    <b>Optimize around my budget</b>
                    <small>
                      {isPremiumUser
                        ? "Premium feature · Balance comfort and cost automatically"
                        : "Premium feature · Upgrade to unlock budget optimization"}
                    </small>
                  </div>
                </div>
                <button
                  type="button"
                  className={premiumOptim ? "switch on" : "switch"}
                  onClick={handleOptimToggle}
                  role="switch"
                  aria-checked={premiumOptim}
                  aria-label={isPremiumUser ? "Optimize around my budget" : "Upgrade to Premium to optimize around your budget"}
                  title={isPremiumUser ? undefined : "Premium feature: see plans"}
                >
                  <i />
                </button>
              </label>

              {premiumOptim && (
                <div className="budget-row single">
                  <label className="field">
                    <span>
                      Total travel budget <em>in US dollars (USD)</em>
                    </span>
                    <div className="input-wrap">
                      <b>$</b>
                      <input
                        value={budgetVal}
                        onChange={(e) => setBudgetVal(e.target.value)}
                        placeholder="e.g. 1500 or 4500"
                      />
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
            {/* Steps 1-2 only move forward ("Next"); planning (and its "thinking" state) belongs to the
                last step. isLoading is also true while a saved trip re-plans in the background. */}
            <button
              className="btn btn-primary"
              disabled={(step === 3 && (isLoading || !!notesError)) || (step === 1 && step1Missing)}
              title={step === 1 && step1Missing ? "Enter a destination city and country"
                : step === 3 && notesError ? notesError : undefined}
              onClick={() => (step < 3 ? setStep(step + 1) : handleFinish())}
            >
              {step < 3 ? (
                <>Next <Icon name="arrow" size={17} /></>
              ) : isLoading ? (
                <span>AI Agent thinking...</span>
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

// Destination hero photos, cached for the browser session (the backend caches
// too), so re-rendering or revisiting Explore never re-requests the same city.
const destinationImageCache = new Map<string, DestinationImage | null>();

function useDestinationImage(city: string, country: string) {
  const key = `${city.toLowerCase()}|${country.toLowerCase()}`;
  const [image, setImage] = useState<DestinationImage | null>(() => destinationImageCache.get(key) ?? null);
  useEffect(() => {
    if (!city) {
      setImage(null);
      return;
    }
    if (destinationImageCache.has(key)) {
      setImage(destinationImageCache.get(key) ?? null);
      return;
    }
    let cancelled = false;
    setImage(null);
    api
      .getDestinationImage(city, country)
      .then((img) => {
        destinationImageCache.set(key, img);
        if (!cancelled) setImage(img);
      })
      .catch(() => {
        if (!cancelled) setImage(null); // network error: fallback now, retry on a later visit
      });
    return () => {
      cancelled = true;
    };
  }, [key, city, country]);
  // The photo itself failed to load: remember that and show the fallback.
  const onError = () => {
    destinationImageCache.set(key, null);
    setImage(null);
  };
  return { image, onError };
}

function ExploreEmpty({ go }: { go: (v: View) => void }) {
  return (
    <main className="app-bg explore">
      <section className="ex-empty page-shell">
        <span className="icon-box yellow">
          <Icon name="pin" />
        </span>
        <span className="kicker">EXPLORE</span>
        <h1>Your next journey starts with a plan.</h1>
        <p>
          Tell MYMILE where you're headed and when. Your stay, travel essentials, weather and
          essentials will appear here for that trip.
        </p>
        <button className="btn btn-yellow" onClick={() => go("plan")}>
          Plan Your Miles, Discover Your Smile <Icon name="arrow" size={16} />
        </button>
      </section>
    </main>
  );
}

function ExploreStatus({
  status,
  message,
  onRetry,
  go,
}: {
  status: "loading" | "error";
  message?: string;
  onRetry?: () => void;
  go: (v: View) => void;
}) {
  return (
    <main className="app-bg explore">
      <section className="ex-empty page-shell" aria-live="polite">
        {status === "loading" ? (
          <>
            <span className="ex-spinner" aria-hidden="true" />
            <h1>Preparing your trip…</h1>
            <p>Checking the weather, stays and travel essentials for your destination.</p>
          </>
        ) : (
          <>
            <span className="icon-box yellow">
              <Icon name="cloud" />
            </span>
            <h1>We couldn't load your trip.</h1>
            <p>{message || "Please check your connection and try again."}</p>
            <div className="ex-empty-actions">
              {onRetry && (
                <button className="btn btn-primary" onClick={onRetry}>
                  Try again
                </button>
              )}
              <button className="btn btn-secondary" onClick={() => go("plan")}>
                Plan a trip
              </button>
            </div>
          </>
        )}
      </section>
    </main>
  );
}

// What switching hotels did to the Premium budget. Uses only the hotels' totals and
// the recalculated budget; nothing is shown that the data doesn't contain.
function BudgetImpactSummary({ impact }: { impact: BudgetImpact }) {
  const cur = impact.currency;
  const total = (v: number | null) => (v == null ? "Price not listed" : formatMoney(v, cur));
  const delta =
    impact.direction === "increase" ? `+${formatMoney(impact.difference ?? 0, cur)}`
      : impact.direction === "decrease" ? `−${formatMoney(Math.abs(impact.difference ?? 0), cur)}`
        : impact.direction === "same" ? "No change" : null;
  return (
    <div className={`ex-impact ${impact.direction}`} role="status" aria-live="polite">
      <div className="ex-impact-main">
        <span className="ex-impact-label">Budget impact</span>
        <span className="ex-impact-change">
          {impact.previousName && (
            <>
              <s title={impact.previousName}>{total(impact.previousTotal)}</s>
              <Icon name="arrow" size={13} />
            </>
          )}
          <b title={impact.nextName}>{total(impact.nextTotal)}</b>
          {delta && <em>{delta}</em>}
        </span>
      </div>
      <div className="ex-impact-meta">
        <span>
          {impact.previousName ? `${impact.previousName} → ${impact.nextName}` : impact.nextName}
        </span>
        {impact.direction === "unknown" ? (
          <span>Budget unchanged: no listed price for this hotel.</span>
        ) : impact.remaining != null ? (
          <span className={impact.remaining < 0 ? "over" : undefined}>
            {impact.remaining < 0 ? "Over-allocated by " : "Unallocated "}
            {formatMoney(Math.abs(impact.remaining), cur)}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function Results({
  plan,
  go,
  userPlan,
  onSelectHotel,
  selectedHotel,
  budgetImpact,
}: {
  plan: TripPlan;
  go: (v: View) => void;
  userPlan: "free" | "premium";
  onSelectHotel: (h: Hotel) => void;
  selectedHotel: Hotel | null;
  budgetImpact: BudgetImpact | null;
}) {
  const [showAgGrid, setShowAgGrid] = useState<boolean>(true);

  const baseHotel = selectedHotel || plan.recommended_hotel;
  // Premium = backend says Premium now (GET /auth/me, expiry-aware) AND this plan
  // was generated for Premium. Expired/stale Premium behaves as Free.
  const isPremium = isPremiumView(userPlan, plan);

  // Live hotels (Google Hotels via SerpApi): provider booking links are fetched
  // once per hotel, only for Premium, only for the hotel being shown. The backend
  // caches them, so this never costs more than one SerpApi search per hotel/stay.
  const [offers, setOffers] = useState<Record<string, HotelOffers | "loading" | "error">>({});
  const offersState = offers[baseHotel.id];
  const wantsOffers = needsOffers(baseHotel, isPremium);
  useEffect(() => {
    if (!wantsOffers || offersState !== undefined) return;
    const id = baseHotel.id;
    setOffers((prev) => ({ ...prev, [id]: "loading" }));
    api
      .getHotelOffers(offersRequest(plan, baseHotel))
      .then((res) => setOffers((prev) => ({ ...prev, [id]: res })))
      .catch(() => setOffers((prev) => ({ ...prev, [id]: "error" })));
  }, [wantsOffers, offersState, baseHotel, plan]);
  const loadedOffers = offersState && typeof offersState === "object" ? offersState : null;
  const activeHotel = mergeOffers(baseHotel, loadedOffers);
  const liveHotel = isLiveHotel(activeHotel);
  // Budget Snapshot + Estimated Cost exist only for Premium (Free never receives the data).
  const showBudget = canShowBudget(userPlan, plan);
  const budget = showBudget ? plan.budget_breakdown : null;
  const nights = plan.total_days;
  // Must match GUESTS_PER_ROOM in the backend hotel service.
  const rooms = Math.max(1, Math.ceil(plan.travelers / 2));
  const price = priceView(activeHotel, nights, rooms);
  const booking = isPremium ? bookingView(activeHotel) : null;

  const budgetParts = budget
    ? BUDGET_PARTS.map((p) => ({ ...p, value: Number(budget[p.key]) || 0 })).filter((p) => p.value > 0)
    : [];
  const partsTotal = budgetParts.reduce((s, p) => s + p.value, 0) || 1;
  const userBudget = budget?.user_budget || null;
  // Same backend numbers, clearer terms (allocated vs estimated, unallocated vs over-allocated).
  const bView = budget ? budgetView(budget) : null;
  const usedPct = bView ? bView.allocatedPct : null;
  const remaining = bView ? bView.unallocated : null;
  const overBudget = bView?.state === "over";

  // Hero: a real, verified photo of THIS destination (backend: Wikipedia /
  // Wikimedia Commons, cached), else a branded fallback. Never a random image.
  const { city: heroCity, country: heroCountry } = heroLocation(plan);
  const hero = useDestinationImage(heroCity, heroCountry);
  // The bundled hero photo shows Cairo/Giza: a valid fallback for Cairo only.
  const cairoPhoto = /^(cairo|giza)$/i.test(heroCity) ? editorHeroImage : null;

  const scrollTo = (id: string) =>
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });


  return (
    <main className="app-bg explore">
      {/* ---------- Hero ---------- */}
      <section className={`ex-hero page-shell${hero.image || cairoPhoto ? "" : " ex-hero-fallback"}`}>
        {hero.image ? (
          <img src={hero.image.url} alt={`${plan.destination}`} onError={hero.onError} />
        ) : cairoPhoto ? (
          <img src={cairoPhoto} alt={`${plan.destination}`} />
        ) : null}
        {hero.image?.page_url && (
          <a className="ex-hero-credit" href={hero.image.page_url} target="_blank" rel="noopener noreferrer">
            Photo: {hero.image.source}
          </a>
        )}
        <div className="ex-hero-content">
          <span className="status-pill">
            <i /> YOUR PLAN IS READY · {isPremium ? "PREMIUM OPTIMIZED" : "FREE PLAN"}
          </span>
          <h1>{plan.destination}</h1>
          {plan.destination_summary && <p className="ex-hero-summary">{plan.destination_summary}</p>}
          <p className={`ex-ai-note ${aiPlanLabel(plan.ai).kind}`}>
            <Icon name="spark" size={14} /> {aiPlanLabel(plan.ai).text}
          </p>
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
              {budget && (
                <div className="ex-stat">
                  <span className="icon-box yellow">
                    <Icon name="wallet" />
                  </span>
                  <div>
                    <small>{bView!.totalLabel}</small>
                    <b>{formatMoney(budget.total_estimated, budget.currency)}</b>
                    <em className={overBudget ? "bad" : "good"}>{bView!.statusLabel}</em>
                  </div>
                </div>
              )}
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

            <article className={`ex-card ex-hotel${activeHotel.is_placeholder ? " placeholder" : ""}`}>
              <div className="ex-hotel-img">
                <img src={activeHotel.image_url} alt={activeHotel.is_placeholder ? "" : activeHotel.name} />
                {!activeHotel.is_placeholder && activeHotel.is_best_match && (
                  <span className="ex-badge">
                    <Icon name="spark" size={13} /> BEST MATCH
                  </span>
                )}
                {activeHotel.image_is_illustrative && (
                  <span className="ex-photo-note">Illustrative photo, not this property</span>
                )}
              </div>
              <div className="ex-hotel-body">
                <div className="ex-hotel-top">
                  <span className="ex-hotel-kind">{activeHotel.category}</span>
                  {activeHotel.rating > 0 && (
                    <span className="ex-rating">
                      <Icon name="star" size={14} /> {activeHotel.rating}
                      {activeHotel.reviews_count ? (
                        <small>({activeHotel.reviews_count.toLocaleString()})</small>
                      ) : null}
                    </span>
                  )}
                </div>
                <h3>{activeHotel.name}</h3>
                <p className="ex-muted">
                  <Icon name="pin" size={14} /> {activeHotel.location}
                </p>
                {activeHotel.amenities.length > 0 && (
                  <p className="ex-amenity-line">{activeHotel.amenities.slice(0, 4).join(" · ")}</p>
                )}
                <p className="ex-hotel-why">{activeHotel.best_match_reason}</p>

                <div className="ex-hotel-foot">
                  <div className="ex-price">
                    <div className="ex-price-total">
                      <b>{price.total}</b>
                      {showsEstimateLabel(price) && <EstimatedLabel />}
                    </div>
                    <small>
                      {price.nightly} · {price.details}
                    </small>
                    {priceMeta(activeHotel, price) && (
                      <small className="ex-price-meta" title={`${price.totalLabel}. ${price.note}`}>
                        {priceMeta(activeHotel, price)}
                      </small>
                    )}
                  </div>
                  {booking ? (
                    <div className="ex-booking">
                      <a
                        href={booking.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="btn btn-primary"
                        title={booking.note}
                      >
                        {booking.label} <Icon name="arrow" size={16} />
                      </a>
                      {bookingPriceLine(activeHotel) && <small>{bookingPriceLine(activeHotel)}</small>}
                      {otherOffers(activeHotel).length > 0 && (
                        <small className="ex-other-offers">
                          Also on{" "}
                          {otherOffers(activeHotel).map((o, i) => (
                            <span key={o.provider}>
                              {i > 0 && " · "}
                              <a href={o.url!} target="_blank" rel="noopener noreferrer"
                                 title={o.price_per_night != null ? PRICE_VARIES_NOTE : undefined}>
                                {o.provider}
                                {o.price_per_night != null && ` ${formatMoney(o.price_per_night, o.currency)}`}
                              </a>
                            </span>
                          ))}
                        </small>
                      )}
                    </div>
                  ) : isPremium && liveHotel && !activeHotel.is_placeholder ? (
                    <div className="ex-booking">
                      {offersState === "loading" ? (
                        <small className="ex-booking-status">Checking booking sites…</small>
                      ) : (
                        <small className="ex-booking-status" title={loadedOffers?.message || undefined}>
                          No direct booking link available for this hotel.
                        </small>
                      )}
                    </div>
                  ) : !isPremium && !(liveHotel && activeHotel.is_placeholder) ? (
                    <button className="btn btn-secondary" onClick={() => go("pricing")}>
                      <Icon name="spark" size={15} /> Unlock booking link
                    </button>
                  ) : null}
                </div>

                <div className="ex-hotel-fine">
                  {isPremium && activeHotel.official_website && (
                    <a href={activeHotel.official_website} target="_blank" rel="noopener noreferrer"
                       title="The hotel's own website (not a booking provider)">
                      Hotel website <Icon name="arrow" size={12} />
                    </a>
                  )}
                  <p>{priceDisclaimer(activeHotel)}</p>
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
                {budget && budgetImpact && budgetImpact.tripId === plan.trip_id && (
                  <BudgetImpactSummary impact={budgetImpact} />
                )}
                {budget && (
                  <>
                    <div className="ex-grid-head second">
                      <span className="kicker">WHERE YOUR MONEY GOES</span>
                      <h3>Expense analytics</h3>
                      <p>Each category balanced by the MYMILE budget agent.</p>
                    </div>
                    <AgGridBudgetTable breakdown={budget} userBudget={budget.user_budget || undefined} />
                  </>
                )}
              </div>
            )}
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
            </div>
            {plan.travel_essentials.length === 0 && (
              <p className="ex-products-empty">{essentialsEmptyMessage(plan.essentials)}</p>
            )}
            {plan.travel_essentials.length > 0 && missingCategoriesNote(plan.essentials) && (
              <p className="ex-products-empty">{missingCategoriesNote(plan.essentials)}</p>
            )}
            <div className="ex-products">
              {plan.travel_essentials.map((prod) => (
                <ProductCard key={prod.id} product={prod} isPremium={isPremium} onUpgrade={() => go("pricing")} />
              ))}
            </div>

            {/* key: a new trip starts with an empty search (nothing carried over from the last trip) */}
            <ProductSearch key={plan.trip_id} audience={plan.shopping_audience} isPremium={isPremium} onUpgrade={() => go("pricing")} />
          </section>
        </div>

        {/* ---------- Sidebar ---------- */}
        <aside className="ex-aside">
          {budget && (
          <div className="ex-card ex-budget">
            <div className="ex-budget-head">
              <h3>Budget snapshot</h3>
              <span className={overBudget ? "bad" : "good"}>{bView!.statusLabel}</span>
            </div>
            <div className="ex-budget-total">
              <small>{bView!.totalLabel}</small>
              <b>{formatMoney(budget.total_estimated, budget.currency)}</b>
              {userBudget && usedPct !== null && (
                <span>
                  of {money(userBudget)} total budget · {usedPct}% allocated
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
            {bView!.mode === "allocated" && (
              <ul className="ex-legend">
                <li><span>Hotel cost</span><b>{money(bView!.hotel)}</b></li>
                <li><span>Category allocations</span><b>{money(bView!.categories)}</b></li>
              </ul>
            )}
            {remaining !== null && (
              <div className={`ex-remaining${overBudget ? " bad" : ""}`}>
                <span>{bView!.unallocatedLabel}</span>
                <b>{money(Math.abs(remaining))}</b>
              </div>
            )}
            <p className="ex-premium-note">{bView!.note}</p>
            <p className="ex-premium-note">
              <Icon name="check" size={15} /> Premium budget optimizer active
            </p>
          </div>
          )}

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

        </aside>
      </div>
    </main>
  );
}

type ChatEntry = {
  role: 'user' | 'assistant';
  text: string;
  local?: boolean;  // UI note, not sent to the AI as history
  generatedBy?: 'groq' | 'gemini' | 'unavailable';
  tools?: string[];
  hotelOptions?: Hotel[];
  suggestedHotelId?: string | null;
};

function Assistant({
  trip,
  userPlan,
  onSelectHotel,
}: {
  trip: TripPlan | null;
  userPlan: 'free' | 'premium';
  onSelectHotel: (hotel: Hotel) => void;
}) {
  const [messages, setMessages] = useState<ChatEntry[]>([
    {
      role: 'assistant',
      local: true,
      text: trip
        ? `Ask me to find a cheaper hotel, check the weather, or what to pack for your ${trip.destination} trip.`
        : `Plan a trip first, then I can help with its hotels and packing. You can still ask general travel questions.`,
    },
  ]);
  const [text, setText] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>(DEFAULT_SUGGESTIONS);
  const lastAi = [...messages].reverse().find((m) => m.generatedBy);
  const canSeeBudget = !!trip && canShowBudget(userPlan, trip);

  const send = async (value = text) => {
    if (!value.trim() || isThinking) return;
    const userMsg = value.trim();
    const history = recentHistory(messages);
    setMessages((prev) => [...prev, { role: 'user', text: userMsg }]);
    setText("");
    setIsThinking(true);

    try {
      const res = await api.chatWithCompanion({
        message: userMsg,
        history,
        current_trip_context: trip ? buildChatContext(trip, canSeeBudget) : undefined,
      });
      setMessages((prev) => [...prev, {
        role: 'assistant',
        text: res.reply,
        generatedBy: res.generated_by,
        tools: res.tools_called,
        hotelOptions: res.hotel_options,
        suggestedHotelId: res.suggested_hotel_id,
      }]);
      if (res.suggestions?.length) setSuggestions(res.suggestions);
    } catch (err) {
      // Never pretend something was done: say the request failed.
      setMessages((prev) => [...prev, {
        role: 'assistant',
        local: true,
        generatedBy: 'unavailable',
        text: `I couldn't reach the assistant: ${getErrorMessage(err)} Nothing in your plan was changed.`,
      }]);
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
                <i /> {trip ? trip.destination : "No trip loaded"} ({userPlan.toUpperCase()})
              </p>
            </div>
          </div>
          <span className="text-xs bg-blue-100 text-blue-800 font-bold px-2.5 py-1 rounded-full">
            {aiProviderName(lastAi?.generatedBy) ? `${aiProviderName(lastAi?.generatedBy)} AI` : lastAi ? "AI unavailable" : "AI assistant"}
          </span>
        </div>

        <div className="chat-body">
          {messages.map((m, i) => {
            const suggested = suggestedHotel(m.hotelOptions || [], m.suggestedHotelId);
            return (
              <div key={i} className={m.role === 'assistant' ? "ai-message" : "user-message"}>
                {m.role === 'assistant' && (
                  <span className="icon-box blue">
                    <Icon name="spark" size={18} />
                  </span>
                )}
                <div>
                  <p>{m.text}</p>
                  {aiProviderName(m.generatedBy) && (
                    <small className="chat-meta">
                      {aiProviderName(m.generatedBy)}{m.tools?.length ? ` · used ${toolList(m.tools)}` : ""}
                    </small>
                  )}
                  {suggested && trip && (
                    <div className="chat-card">
                      <b>{suggested.name}</b>
                      <small>
                        {suggested.price_per_night != null
                          ? `${formatMoney(suggested.price_per_night, suggested.currency)} / night`
                          : "Price not listed"}
                        {suggested.rating ? ` · ★ ${suggested.rating}` : ""}
                      </small>
                      <button className="btn btn-secondary" onClick={() => onSelectHotel(suggested)}>
                        Use this hotel
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {isThinking && (
            <div className="ai-message">
              <span className="icon-box blue">
                <Icon name="spark" size={18} />
              </span>
              <div>
                <span className="thinking">
                  <i />
                  <i />
                  <i /> Thinking…
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="suggestions">
          {suggestions.map((x) => (
            <button onClick={() => send(x)} key={x} disabled={isThinking}>
              {x}
            </button>
          ))}
        </div>

        <div className="chat-input">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Ask anything about your trip, hotels, or packing..."
          />
          <button onClick={() => send()} aria-label="Send" disabled={isThinking}>
            <Icon name="send" />
          </button>
        </div>
      </div>
    </main>
  );
}

// The product's own image from Channel3, or a neutral placeholder (never a stock photo).
function ProductImage({ product, className }: { product: Product; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (!product.image_url || failed) {
    return (
      <div className={`product-img-empty ${className || ""}`} aria-label="No product image">
        <Icon name="bag" size={22} />
      </div>
    );
  }
  return <img src={product.image_url} alt={product.name} className={className} onError={() => setFailed(true)} />;
}

// One product card: real Channel3 data and a "View Product" button that opens the
// retailer's own URL. The backend sends that URL only to Premium accounts; without a
// valid URL the button is disabled (never a made-up or broken link).
function ProductCard({ product: prod, isPremium, onUpgrade }: { product: Product; isPremium: boolean; onUpgrade: () => void }) {
  const url = viewProductUrl(prod);
  return (
    <article className="ex-card ex-product">
      <ProductImage product={prod} />
      <div>
        {(prod.group || productSource(prod)) && (
          <span className="ex-product-cat">
            {[prod.group, audienceLabel(prod)].filter(Boolean).join(" · ") || productSource(prod)}
          </span>
        )}
        <h4>{prod.name}</h4>
        {prod.brand && <small className="ex-product-brand">{prod.brand}</small>}
        {prod.reason && <p>{prod.reason}</p>}
      </div>
      <div className="ex-product-foot">
        <b>
          {productPrice(prod)}
          {availabilityLabel(prod) && <small className="ex-product-stock">{availabilityLabel(prod)}</small>}
        </b>
        {url ? (
          <a className="btn btn-yellow btn-small" href={url} target="_blank" rel="noopener noreferrer">
            View Product
          </a>
        ) : (
          <button className="btn btn-yellow btn-small" disabled
                  title={isPremium ? "No retailer link was provided for this product" : "Retailer links are included with Premium"}>
            View Product
          </button>
        )}
      </div>
      {!url && !isPremium && (
        <button className="ex-product-buy" onClick={onUpgrade}>Retailer links with Premium ✦</button>
      )}
    </article>
  );
}

// Manual product search inside Travel Essentials: the exact words the user types go to
// GET /api/products/search (a direct, cached Channel3 search; no AI call).
function ProductSearch({ audience, isPremium, onUpgrade }: {
  audience?: "men" | "women" | "all" | null;
  isPremium: boolean;
  onUpgrade: () => void;
}) {
  const [input, setInput] = useState("");
  const [state, setState] = useState<{
    loading: boolean; lastQuery: string | null; failed: boolean; products: Product[]; message: string | null;
  }>({ loading: false, lastQuery: null, failed: false, products: [], message: null });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const query = manualSearchQuery(input, state);
    if (!query) return;
    setState((s) => ({ ...s, loading: true, message: null }));
    try {
      const res = await api.searchProducts(query, audience);
      const message = res.products.length ? null
        : res.status === "empty" ? `No products found for "${query}".`
          : res.message || "Product search isn't available right now.";
      setState({ loading: false, lastQuery: query, failed: res.status !== "ok" && res.status !== "empty",
                 products: res.products, message });
    } catch (err) {
      setState({ loading: false, lastQuery: query, failed: true, products: [],
                 message: `The search failed: ${getErrorMessage(err)}` });
    }
  };

  return (
    <div className="ex-search" aria-live="polite">
      <form className="ex-search-form" onSubmit={submit} role="search">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="What product are you looking for?"
          maxLength={120}
          aria-label="Search for a product"
        />
        <button className="btn btn-primary btn-small" type="submit" disabled={state.loading || !input.trim()}>
          {state.loading ? "Searching…" : "Search"}
        </button>
      </form>
      {state.lastQuery && !state.loading && (
        <div className="ex-search-results">
          <span className="kicker">YOUR SEARCH · CHANNEL3</span>
          <h3>Results for "{state.lastQuery}"</h3>
          {state.message && <p className="ex-products-empty">{state.message}</p>}
          {state.products.length > 0 && (
            <div className="ex-products">
              {state.products.map((prod) => (
                <ProductCard key={prod.id} product={prod} isPremium={isPremium} onUpgrade={onUpgrade} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Pricing({
  authUser,
  premiumTerms,
  plansError,
  go,
  refreshUser,
  onSessionExpired,
}: {
  authUser: User | null;              // null = guest (always Free)
  premiumTerms: PremiumTerms | null;  // from GET /api/subscriptions/plans
  plansError: boolean;
  go: (v: View) => void;
  refreshUser: () => Promise<boolean>;
  onSessionExpired: () => void;
}) {
  // Display only: the plan always comes from the backend (/auth/me).
  const userPlan: 'free' | 'premium' = authUser?.plan === 'premium' ? 'premium' : 'free';
  const durationDays = premiumTerms?.duration_days;
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
          <button className="btn btn-secondary full-btn" disabled>
            {userPlan === 'free' ? 'Current Plan' : 'Included with Premium'}
          </button>
          {[
            "AI travel planning",
            "Hotel recommendations & estimates",
            "Live meteorological weather insights",
            "Channel3 travel essentials discovery",
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
            {formatPremiumPrice(premiumTerms)}
            <small>{durationDays ? ` for ${durationDays} days` : ""}</small>
          </h2>
          <p>
            {premiumTerms
              ? `One-time payment of ${formatPremiumPrice(premiumTerms)} (${premiumTerms.currency}) for ${durationDays} days of Premium. No subscription, no automatic renewal.`
              : plansError
                ? "Premium pricing is unavailable right now. Please try again later."
                : "Loading Premium pricing…"}
          </p>
          {userPlan === 'premium' ? (
            <div className="rounded-xl bg-white/90 border border-yellow-300 p-3 text-sm font-semibold text-gray-900">
              ✓ Premium active
              {authUser?.premium_until ? ` until ${formatExpiry(authUser.premium_until)}` : ""}
            </div>
          ) : !authUser ? (
            <button className="btn btn-yellow full-btn" onClick={() => go("login")}>
              Get Premium · {premiumTerms ? formatPremiumPrice(premiumTerms) : "$9"}/month
            </button>
          ) : premiumTerms ? (
            <PremiumCheckout
              refreshUser={refreshUser}
              onSessionExpired={onSessionExpired}
              premiumUntilLabel={formatExpiry}
            />
          ) : null}
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

function Trips({
  go,
  trips,
  onOpenTrip,
}: {
  go: (v: View) => void;
  trips: StoredTrips;
  onOpenTrip: (id: string) => void;
}) {
  return (
    <main className="app-bg simple-page wide">
      <div className="page-intro left">
        <span className="kicker">YOUR JOURNEYS</span>
        <h1>Trips worth looking forward to.</h1>
        <p>
          {trips.trips.length
            ? "Open a trip to see it in Explore. The active trip is the one Explore shows."
            : "You haven't planned a trip yet. Start one and it will appear here."}
        </p>
      </div>
      <div className="trip-list">
        {trips.trips.map((t) => {
          const active = t.id === trips.activeId;
          const days = Math.max(
            1,
            Math.round((Date.parse(t.return_date) - Date.parse(t.departure_date)) / 86400000) || 1
          );
          return (
            <article
              key={t.id}
              className={`saved-trip no-img cursor-pointer${active ? " active" : ""}`}
              onClick={() => onOpenTrip(t.id)}
            >
              <div>
                <span className="status-pill">
                  <i /> {active ? "ACTIVE TRIP" : "SAVED TRIP"}
                </span>
                <h2>{t.destination_city}, {t.destination_country}</h2>
                <p>
                  {formatTripDates(t.departure_date, t.return_date)} · {t.travelers} traveler
                  {t.travelers > 1 ? "s" : ""} · {t.purpose}
                </p>
                <div className="trip-meta">
                  <span>
                    <Icon name="calendar" size={16} /> {days} day{days === 1 ? "" : "s"}
                  </span>
                  <span>
                    <Icon name="hotel" size={16} /> {t.stay_preference}
                  </span>
                </div>
              </div>
              <button
                aria-label={`Open ${t.destination_city} in Explore`}
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenTrip(t.id);
                }}
              >
                <Icon name="arrow" />
              </button>
            </article>
          );
        })}

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
  go
}: {
  user: User;
  go: (v: View) => void;
}) {
  return (
    <main className="app-bg simple-page wide">
      <div className="profile-layout">
        <aside>
          <div className="profile-avatar">{getInitials(user.name)}</div>
          <h2>{user.name}</h2>
          <p>{user.email}</p>
          {/* Display only: the plan comes from the backend (/auth/me). */}
          <span
            className={`premium-pill mt-2 font-bold ${
              user.plan === 'premium' ? 'bg-yellow-400 text-gray-900' : 'bg-gray-200 text-gray-700'
            }`}
          >
            <Icon name="spark" size={13} /> {user.plan.toUpperCase()}
          </span>
          {user.plan === 'premium' && user.premium_until && (
            <p className="text-xs text-gray-500 mt-1">Premium until {formatExpiry(user.premium_until)}</p>
          )}
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

function Footer({ go }: { go: (v: View) => void }) {
  return (
    <footer>
      <div className="page-shell footer-grid">
        <div>
          <img src={logo} alt="MYMILE" className="h-8 w-auto mb-3" />
          <p>Your intelligent travel companion for happier journeys, every mile.</p>
          <div className="mt-3 text-xs text-slate-400">
            Powered by Channel3, AG Grid, Open-Meteo & Groq
          </div>
        </div>
        <div>
          <b>Explore</b>
          <button onClick={() => go("plan")}>Plan a trip</button>
          <button onClick={() => go("results")}>Dashboard</button>
          <button onClick={() => go("pricing")}>Pricing Plans</button>
        </div>
        <div>
          <b>Developers</b>
          <a href="/docs" target="_blank" rel="noreferrer" className="block text-slate-400 text-sm hover:text-white py-1">
            FastAPI Docs ↗
          </a>
          <a href="/openapi.json" target="_blank" rel="noreferrer" className="block text-slate-400 text-sm hover:text-white py-1">
            OpenAPI Spec ↗
          </a>
        </div>
      </div>
      <div className="page-shell copyright">
        <span>© 2026 MYMILE. Your smile, with you every mile.</span>
        <span>Channel3 · AG Grid · Groq</span>
      </div>
    </footer>
  );
}

// A cached user (localStorage/sessionStorage) is never trusted for Premium: it
// is shown as Free until GET /auth/me confirms the real, expiry-aware plan.
function unverified(u: User | null): User | null {
  return u ? { ...u, plan: "free", premium_until: null } : null;
}

export default function App() {
  const [view, setView] = useState<View>("home");
  // The logged-in account (null = guest). Guests are always Free.
  const [authUser, setAuthUser] = useState<User | null>(() => unverified(getStoredUser<User>()));
  // Effective plan, as last reported by the backend.
  const userPlan: "free" | "premium" = authUser?.plan === "premium" ? "premium" : "free";

  // True once the saved session (if any) has been confirmed or rejected by /auth/me.
  const [authChecked, setAuthChecked] = useState(() => !getStoredToken());
  const [premiumTerms, setPremiumTerms] = useState<PremiumTerms | null>(null);
  const [plansError, setPlansError] = useState(false);

  const handleSessionExpired = useCallback(() => {
    api.logout();
    setAuthUser(null);
    setView("login");
  }, []);

  // GET /auth/me is the source of truth for the plan. Resolves true if Premium.
  const refreshUser = useCallback(async (): Promise<boolean> => {
    try {
      const me: User = await api.getMe();
      setAuthUser(me);
      updateStoredUser(me);
      return me.plan === "premium";
    } catch (err: any) {
      if (err?.response?.status === 401) {
        handleSessionExpired();
        throw new SessionExpiredError();
      }
      throw err;
    }
  }, [handleSessionExpired]);

  // On load: confirm a saved session with the server, and fetch public plan terms.
  useEffect(() => {
    if (getStoredToken()) {
      // Network failures keep the (unverified, Free) session; 401 logs out.
      refreshUser().catch(() => undefined).finally(() => setAuthChecked(true));
    }
    api
      .getPlans()
      .then((plans) => {
        const p = plans?.premium;
        if (p && p.price != null && p.currency && p.duration_days) {
          setPremiumTerms({
            price: String(p.price),
            currency: p.currency,
            duration_days: p.duration_days,
            one_time: p.one_time !== false,
            auto_renew: p.auto_renew === true,
          });
        } else {
          setPlansError(true);
        }
      })
      .catch(() => setPlansError(true));
  }, [refreshUser]);

  const [currentTrip, setCurrentTrip] = useState<TripPlan | null>(null);
  const [selectedHotel, setSelectedHotel] = useState<Hotel | null>(null);
  // Effect of the latest hotel switch on the Premium budget (shown under the comparison grid).
  const [budgetImpact, setBudgetImpact] = useState<BudgetImpact | null>(null);
  // ---- Planned trips: the source of truth for Explore ----
  // Stored per account as the Plan a Trip REQUEST (see services/tripStore.ts). The
  // plan itself always comes from the server, which re-decides Premium content.
  // There is no default/demo trip: Explore stays empty until the user plans one.
  const account = accountKey(authUser?.id);
  const [trips, setTrips] = useState<StoredTrips>(() => loadTrips(browserStore(), account));
  const [tripStatus, setTripStatus] = useState<"idle" | "loading" | "ready" | "error">(() =>
    getActiveTrip(loadTrips(browserStore(), account)) ? "loading" : "idle"
  );
  const [tripError, setTripError] = useState("");
  const isLoading = tripStatus === "loading";
  const planSeq = useRef(0);
  const lastRequest = useRef<TripRequest | null>(null);
  const userPlanRef = useRef(userPlan);
  userPlanRef.current = userPlan;

  // Plan (or re-plan) a trip with ALL of its fields. Only the latest request may
  // update Explore, so a slower, older response can never replace a newer trip.
  const runPlan = useCallback(async (trip: TripRequest): Promise<boolean> => {
    const seq = ++planSeq.current;
    lastRequest.current = trip;
    setTripStatus("loading");
    setTripError("");
    try {
      const plan = await api.planTrip(toPlanPayload(trip, userPlanRef.current));
      if (seq !== planSeq.current) return false;
      setCurrentTrip(plan);
      setSelectedHotel(plan.recommended_hotel);
      setBudgetImpact(null);
      setTripStatus("ready");
      return true;
    } catch (err) {
      if (seq !== planSeq.current) return false;
      setTripStatus("error");
      setTripError(getErrorMessage(err, "Your trip could not be planned. Please try again."));
      return false;
    }
  }, []);

  // On load, and whenever the account or its server-verified plan changes
  // (login, logout, upgrade, expiry): show THIS account's active trip, re-planned
  // so Premium content matches the current entitlement. Waits for /auth/me.
  const tripKey = `${authChecked}:${account}:${userPlan}`;
  useEffect(() => {
    if (!authChecked) return;
    const stored = loadTrips(browserStore(), account);
    setTrips(stored);
    const active = getActiveTrip(stored);
    if (active) {
      void runPlan(active);
    } else {
      planSeq.current += 1; // ignore anything still in flight for the previous account
      setCurrentTrip(null);
      setSelectedHotel(null);
      setBudgetImpact(null);
      setTripStatus("idle");
    }
  }, [tripKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleGeneratePlan = async (input: TripInput): Promise<boolean> => {
    const trip: TripRequest = { ...input, id: newTripId(), created_at: new Date().toISOString() };
    const ok = await runPlan(trip);
    if (ok) setTrips(saveTrip(browserStore(), account, trip)); // only successful trips are saved
    return ok;
  };

  const handleOpenTrip = (id: string) => {
    const stored = setActiveTrip(browserStore(), account, id);
    setTrips(stored);
    const active = getActiveTrip(stored);
    if (active) {
      void runPlan(active);
      go("results");
    }
  };

  const retryTrip = async () => {
    const trip = lastRequest.current;
    if (!trip) return;
    const ok = await runPlan(trip);
    if (ok && !loadTrips(browserStore(), account).trips.some((t) => t.id === trip.id)) {
      setTrips(saveTrip(browserStore(), account, trip));
    }
  };

  const handleSelectHotel = (hotel: Hotel) => {
    // Same budget recalculation as before (see services/hotelComparison.ts); selecting
    // the hotel that is already selected changes nothing and recalculates nothing.
    const result = applyHotelSelection(currentTrip, selectedHotel, hotel, userPlan);
    if (!result) return;
    setSelectedHotel(result.selectedHotel);
    if (result.trip && result.trip !== currentTrip) setCurrentTrip(result.trip);
    setBudgetImpact(result.impact);
  };

  const go = (v: View) => {
    setView(v);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleAuth = (u: User) => {
    // Login/register responses carry the backend's effective plan.
    setAuthUser(u);
    go("home");
  };

  const handleLogout = () => {
    api.logout();
    setAuthUser(null); // guest = Free
    go("home");
  };

  const content = useMemo(() => {
    if (view === "home") return (
      <Home go={go} premiumTerms={premiumTerms} />
    );
    if (view === "plan") return (
      <Planner
        go={go}
        onGeneratePlan={handleGeneratePlan}
        isLoading={isLoading}
        userPlan={userPlan}
      />
    );
    if (view === "results") {
      if (tripStatus === "loading") return <ExploreStatus status="loading" go={go} />;
      if (tripStatus === "error") {
        return <ExploreStatus status="error" message={tripError} onRetry={retryTrip} go={go} />;
      }
      if (!currentTrip) return <ExploreEmpty go={go} />;
      return (
        <Results
          plan={currentTrip}
          go={go}
          userPlan={userPlan}
          onSelectHotel={handleSelectHotel}
          selectedHotel={selectedHotel}
          budgetImpact={budgetImpact}
        />
      );
    }
    if (view === "pricing") return (
      <Pricing
        authUser={authUser}
        premiumTerms={premiumTerms}
        plansError={plansError}
        go={go}
        refreshUser={refreshUser}
        onSessionExpired={handleSessionExpired}
      />
    );
    if (view === "assistant")
      return (
        <Assistant
          trip={currentTrip}
          userPlan={userPlan}
          onSelectHotel={handleSelectHotel}
        />
      );
    if (view === "trips") return <Trips go={go} trips={trips} onOpenTrip={handleOpenTrip} />;
    if (view === "profile") {
      // Guests have no profile: ask them to log in.
      return authUser ? <Profile user={authUser} go={go} /> : <Login go={go} onAuth={handleAuth} />;
    }
    if (view === "signup") return <Signup go={go} onAuth={handleAuth} />;
    return <Login go={go} onAuth={handleAuth} />;
  }, [view, currentTrip, selectedHotel, authUser, userPlan, isLoading, tripStatus, tripError, trips,
      premiumTerms, plansError,
      refreshUser, handleSessionExpired]);

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
        <Footer go={go} />
      )}

    </>
  );
}
