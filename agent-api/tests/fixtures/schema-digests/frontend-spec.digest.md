# FrontendSpec Schema Digest

type FrontendSpec = {
  specVersion: string;
  project: Project;
  theme?: Theme;
  layout?: Layout;
  pages: Page[];
  components?: Component[];
  forms?: Form[];
  content?: ContentCollection[];
  assets?: Asset[];
  app?: AppOutline | null;
  auth?: Record<string, unknown> | null;
  x-backendSpec?: string | null;
};

// A group of roles with its own layout (Story 23.10): its own routes (`prefix`), shell, home and views.
type AppArea = {
  id: string;
  label: string;
  roles: string[];
  prefix?: string;
  design?: AppDesign;
};

// A figure (`kind: figure`) or a chart of an aggregate of an entity's records (Epic 21's aggregates).
type AppDashboardItem = {
  label: string;
  kind?: "figure" | "bar" | "line" | "area" | "pie";
  entity: string;
  fn?: "count" | "sum" | "avg" | "min" | "max";
  field?: string | null;
  filter?: Record<string, string | number | boolean>;
  period?: "day" | "week" | "month" | "year" | null;
  dateField?: string | null;
  groupBy?: string | null;
};

// The design brief (Epic 23): the model chooses from these values, code checks them against the contract and replaces what does not fit (`replaced`, one line each).
type AppDesign = {
  archetype?: "back-office" | "catalogue" | "feed" | "workspace" | "booking" | "learning" | "storefront" | null;
  shell?: "sidebar" | "topbar" | "topbar-tabs" | "rail" | null;
  mobileNav?: "drawer" | "bottom-tabs" | null;
  frame?: "narrow" | "standard" | "wide" | "full" | null;
  density?: "compact" | "comfortable" | "spacious" | null;
  homeView?: "dashboard" | "feed" | "catalogue" | "agenda" | "bento" | "featured" | null;
  mainEntity?: string | null;
  entities?: Record<string, AppEntityDesign>;
  looks?: AppLook[];
  requested?: AppRequestedStyle | null;
  recipe?: "minimal" | "swiss" | "material" | "enterprise" | "soft" | "clay" | "aurora" | "glass" | "brutalist" | "neon" | "playful" | "editorial" | "cinema" | "paper" | "terminal" | "luxe" | null;
  fontPairing?: "neutral" | "geometric" | "editorial" | "bookish" | "workshop" | "loud" | "humanist" | "japanese-gothic" | "japanese-mincho" | null;
  seed?: number | null;
  reason?: string | null;
  replaced?: string[];
};

// How an entity is named and shown; every field is optional (code fills it from the BackendSpec).
type AppEntity = {
  label?: string | null;
  plural?: string | null;
  displayField?: string | null;
  listFields?: string[];
  listStyle?: "table" | "cards" | null;
  detailFields?: string[];
  fieldLabels?: Record<string, string>;
  help?: Record<string, string>;
  create?: "onRecord" | "onOpen" | "page" | null;
};

// How one entity's records are shown (Stories 23.3–23.5).
type AppEntityDesign = {
  view?: "table" | "cards" | "media-grid" | "feed" | "board" | "calendar" | "shelves" | null;
  detailView?: "record" | "media" | "profile" | "media-side" | "split-panel" | "reader" | "watch" | null;
  roles?: AppFieldRoles;
  filtersStyle?: "toolbar" | "chips" | "facets" | "search-first" | null;
  card?: "stacked" | "overlay" | "side" | "text-first" | null;
  aspect?: "wide" | "portrait" | "square" | "auto" | null;
  columns?: number | null;
  groupBy?: string | null;
  dateField?: string | null;
  endField?: string | null;
};

// Which field plays which part on a card or a row (Story 23.3); code checks each against the field's type.
type AppFieldRoles = {
  media?: string | null;
  title?: string | null;
  subtitle?: string | null;
  meta?: string[];
  badge?: string | null;
  stat?: string | null;
  price?: string | null;
  avatar?: string | null;
  duration?: string | null;
};

type AppHighlight = {
  title: string;
  text?: string | null;
  icon?: string | null;
};

// An optional public first page (off unless the requirement asks for one): a headline, a short text, up to three highlights and a button into the app.
type AppLanding = {
  headline: string;
  text?: string | null;
  highlights?: AppHighlight[];
  cta?: string | null;
};

// One look the user can pick (Story 23.7): a style recipe and why it fits.
type AppLook = {
  recipe: "minimal" | "swiss" | "material" | "enterprise" | "soft" | "clay" | "aurora" | "glass" | "brutalist" | "neon" | "playful" | "editorial" | "cinema" | "paper" | "terminal" | "luxe";
  reason?: string | null;
  fontPairing?: "neutral" | "geometric" | "editorial" | "bookish" | "workshop" | "loud" | "humanist" | "japanese-gothic" | "japanese-mincho" | null;
};

type AppNavItem = {
  entity: string;
  label?: string | null;
  icon?: string | null;
};

// What the app is, as the model drafts it: entities, navigation, labels and figures, never layout, routes, operations or parameters (code binds every screen, Story 22.3).
type AppOutline = {
  name?: string | null;
  tagline?: string | null;
  icon?: string | null;
  nav?: AppNavItem[];
  home?: string;
  entities?: Record<string, AppEntity>;
  dashboard?: AppDashboardItem[];
  landing?: AppLanding | null;
  design?: AppDesign | null;
  locale?: string | null;
  areas?: AppArea[];
  workflows?: Record<string, unknown> | null;
};

// What the requirement itself says about the look, as values (2026-11-07): the requirement comes before the design data's choice for its kind of product.
type AppRequestedStyle = {
  accent?: string | null;
  background?: string | null;
  text?: string | null;
  scheme?: "light" | "dark" | null;
  headingFont?: "serif" | "sans" | "geometric" | "rounded" | "display" | "mono" | null;
  corners?: "sharp" | "rounded" | "pill" | null;
  photos?: string | null;
  words?: string | null;
};

// An image the site shows (Stories 15.1, 19.1).
type Asset = {
  id: string;
  kind?: "image" | "icon" | "video" | "file" | "illustration" | "pattern" | "logo";
  alt?: string | null;
  source?: string;
  prompt?: string | null;
  style?: string | null;
  aspectRatio?: "16:9" | "4:3" | "1:1" | "3:4" | "21:9" | null;
  decorative?: boolean;
  credit?: AssetCredit | null;
  query?: string | null;
  place?: "watch" | "background" | null;
  video?: AssetVideo | null;
};

// Epic 27: a stock photo's credit, shown with it as the photo service requires ("Photo by <name> on Unsplash"); Epic 31: a sample video's ("<title> · <channel> on YouTube", "Video by <name> on Pixabay").
type AssetCredit = {
  provider?: "unsplash" | "youtube" | "pixabay";
  name: string;
  profileUrl: string;
  sourceUrl: string;
  photoId?: string | null;
  title?: string | null;
};

// Epic 31 (code-only, written by the drafting code from a provider's hit): what a `video` asset plays.
type AssetVideo = {
  provider: "youtube" | "pixabay";
  id: string;
  title?: string | null;
  url?: string | null;
  poster?: string | null;
  width?: number | null;
  height?: number | null;
  duration?: number | null;
};

type Component = {
  name: string;
  kind?: "primitive" | "composite" | "section" | "layout";
  uses?: string[];
  description?: string | null;
  propsSchema?: Record<string, unknown> | null;
};

type ContentCollection = {
  collection: string;
  records?: Record<string, unknown>[];
};

// Where a section's data comes from: an API operation (dynamic) or a `content` collection (both modes).
type DataBinding = {
  operationId?: string | null;
  collection?: string | null;
  params?: Record<string, unknown>;
  fields?: string[];
};

type Footer = {
  text?: string | null;
  links?: NavLink[];
};

type Form = {
  id: string;
  operationId?: string | null;
  load?: FormLoad | null;
  params?: Record<string, unknown>;
  fields: FormField[];
  submitLabel?: string | null;
  onSuccess?: OnSuccess | null;
};

type FormField = {
  name: string;
  type?: "string" | "text" | "email" | "url" | "tel" | "password" | "integer" | "number" | "decimal" | "boolean" | "date" | "datetime" | "enum";
  label?: string | null;
  required?: boolean;
  hidden?: boolean;
  value?: unknown;
  values?: string[] | null;
  min?: number | null;
  max?: number | null;
  maxLength?: number | null;
  placeholder?: string | null;
  help?: string | null;
  currency?: string | null;
  unit?: string | null;
  reference?: FormFieldReference | null;
  upload?: FormFieldUpload | null;
  transition?: boolean | null;
};

// Epic 22 (app flow only): a reference picked by its name from the parent's list (`x-bga.ref`).
type FormFieldReference = {
  entity: string;
  listOperation: string;
  detailOperation?: string | null;
  labelField?: string | null;
  searchParam?: string | null;
  limitParam?: string | null;
  pageSize?: number | null;
};

// Epic 22 (app flow only, Story 22.7): a file or image uploaded through the storage plugin's presigned URL.
type FormFieldUpload = {
  presign: string;
  entity: string;
  field: string;
  kind?: "file" | "image" | "video" | "audio" | "subtitles";
  accept?: string[];
  maxSize?: number | null;
};

type FormLoad = {
  operationId: string;
  params?: Record<string, unknown>;
};

type Header = {
  logoText?: string | null;
  logo?: string | null;
  navigation?: NavLink[];
};

// Story 20.5: the site's content icons: one set, a weight (Lucide draws thin to bold as stroke widths; fill and duotone need Phosphor) and a treatment (`tile`: a small rounded square in the muted tone).
type IconStyle = {
  set?: "lucide" | "phosphor" | "none";
  weight?: "thin" | "light" | "regular" | "bold" | "fill" | "duotone";
  treatment?: "plain" | "tile";
};

type Layout = {
  shell?: "header-footer" | "sidebar" | "blank";
  header?: Header;
  footer?: Footer;
  chrome?: TreeNode | null;
  footerTree?: TreeNode | null;
};

// Story 20.6: how the site moves.
type MotionStyle = {
  feel?: "none" | "click" | "slide" | "flow" | "drop" | "bounce" | "float" | "cut";
  signature?: "none" | "countUp" | "headlineRise" | "imageUnmask" | "indicator";
};

type NavLink = {
  label: string;
  page?: string | null;
  href?: string | null;
};

type OnSuccess = {
  toast?: string | null;
  navigate?: string | null;
};

type Page = {
  id?: string | null;
  route: string;
  title: string;
  purpose?: string | null;
  seo?: Seo | null;
  rhythm?: "uniform" | "alternate" | "dividers";
  sections?: Section[];
  tree?: TreeNode | null;
  css?: string | null;
};

type Project = {
  name: string;
  description?: string | null;
  mode: "static" | "dynamic";
  locale?: string;
  locales?: string[];
  flow?: string | null;
};

type Section = {
  id: string;
  component: string;
  data?: DataBinding | null;
  form?: string | null;
  content?: Record<string, unknown>;
  states?: SectionStates | null;
  children?: Section[] | null;
};

type SectionStates = {
  loading?: string | null;
  empty?: string | null;
  error?: string | null;
  emptyImage?: string | null;
};

type Seo = {
  title?: string | null;
  description?: string | null;
};

type Theme = {
  style?: "minimal" | "editorial" | "playful" | "corporate" | "dashboard";
  colorScheme?: "light" | "dark" | "light-dark";
  colors?: ThemeColors;
  typography?: Typography;
  radius?: "none" | "sm" | "md" | "lg" | "full" | null;
  density?: "compact" | "comfortable" | null;
  surface?: "flat" | "outline" | "raised" | null;
  colorArea?: "minimal" | "block" | "bold" | null;
  icons?: IconStyle | null;
  motion?: MotionStyle | null;
  direction?: ThemeDirection | null;
};

// CSS colours: hex, or rgb()/hsl()/oklch(); checked in the validator (FE_INVALID_COLOR).
type ThemeColors = {
  primary?: string | null;
  secondary?: string | null;
  accent?: string | null;
  background?: string | null;
  foreground?: string | null;
  muted?: string | null;
  destructive?: string | null;
};

// Where a drafted theme came from (Story 12.6): the design data's product type, landing pattern, palette and font pairing.
type ThemeDirection = {
  productType?: string | null;
  pattern?: string | null;
  palette?: string | null;
  fontPairing?: string | null;
  source?: string | null;
  name?: string | null;
  concept?: string | null;
  engine?: "material" | "scene" | "character" | "tradition" | "medium" | "convention" | null;
  tone?: Tone | null;
  keyVisual?: "photo" | "illustration" | "type" | "product" | "pattern" | null;
  givesUp?: string | null;
  seed?: number | null;
};

// A direction's feel on five scales, 1–5 (Story 20.3, `orchestrator/drafting/design_tone.py`).
type Tone = {
  energy?: number;
  finish?: number;
  density?: number;
  weight?: number;
  seriousness?: number;
};

// Epic 21: one node of a designed page: an HTML element, a shadcn primitive, a Lucide icon, a library section or a data component, with Tailwind classes and props; children are nodes or text.
type TreeNode = {
  type: string;
  props?: Record<string, unknown>;
  children?: (TreeNode | string)[];
};

type Typography = {
  headingFont?: string | null;
  bodyFont?: string | null;
  scale?: "compact" | "default" | "large";
  headingWeight?: 400 | 500 | 600 | 700 | null;
  headingCase?: "normal" | "upper" | null;
  tracking?: "tight" | "normal" | "wide" | null;
  ratio?: "tight" | "default" | "dramatic" | null;
};

type ActionOnSuccess = {
  toast?: string | null;
  navigate?: string | null;
};

type SectionAction = {
  id: string;
  label: string;
  kind?: "link" | "mutation";
  page?: string | null;
  params?: Record<string, unknown>;
  operationId?: string | null;
  body?: Record<string, unknown>;
  confirm?: string | boolean | null;
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link" | null;
  onSuccess?: ActionOnSuccess | null;
};

type ActionBarProps = {
  title?: string | null;
  description?: string | null;
  actions?: SectionAction[];
};

type Cta = {
  label: string;
  page?: string | null;
  href?: string | null;
};

type HeroProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  variant?: "split" | "centered" | "banner" | "stage" | "type" | "stacked" | "collage" | "vertical";
  heading: string;
  eyebrow?: string | null;
  body?: string | null;
  image?: string | null;
  images?: string[] | null;
  backgroundVideo?: string | null;
  cta?: Cta | null;
  secondaryCta?: Cta | null;
};

type FeatureItem = {
  title: string;
  body?: string | null;
  image?: string | null;
  icon?: string | null;
};

type FeaturesProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  description?: string | null;
  items?: FeatureItem[] | null;
  columns?: 2 | 3 | 4 | null;
  cardStyle?: "outline" | "filled" | "plain";
  form?: "cards" | "list" | "ledger" | "alternating";
};

type CallToActionProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  heading: string;
  body?: string | null;
  cta: Cta;
};

type TestimonialItem = {
  quote: string;
  author: string;
  role?: string | null;
};

type TestimonialsProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  items?: TestimonialItem[] | null;
  cardStyle?: "outline" | "filled" | "plain";
  form?: "cards" | "quote" | "strip";
};

type FaqItem = {
  question: string;
  answer: string;
};

type FaqProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  items?: FaqItem[] | null;
};

type PlanItem = {
  name: string;
  price: string | number;
  description?: string | null;
  features?: string[];
  cta?: Cta | null;
  highlighted?: boolean;
  icon?: string | null;
};

type PricingProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  description?: string | null;
  items?: PlanItem[] | null;
  cardStyle?: "outline" | "filled" | "plain";
};

type StatData = {
  operationId: string;
  value?: string;
};

type StatItem = {
  label: string;
  value?: string | number;
  data?: StatData | null;
  icon?: string | null;
};

type StatsProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  items?: StatItem[] | null;
  cardStyle?: "outline" | "filled" | "plain";
  form?: "cards" | "figures" | "inline";
};

type GalleryItem = {
  image: string;
  title?: string | null;
  caption?: string | null;
};

type GalleryProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  items?: GalleryItem[] | null;
  columns?: 2 | 3 | 4 | null;
};

type VideoItem = {
  video: string;
  title?: string | null;
  caption?: string | null;
};

// Epic 31 (Story 31.3): one featured video (`video`) with a heading and a short text, or a grid of two to six videos with their titles (`items`).
type VideoProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  description?: string | null;
  video?: string | null;
  items?: VideoItem[] | null;
  columns?: 2 | 3 | 4 | null;
};

type RichTextProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  heading?: string | null;
  body: string;
};

type ContactInfoProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  email?: string | null;
  phone?: string | null;
  address?: string | null;
  mapUrl?: string | null;
};

type StepItem = {
  title: string;
  body?: string | null;
};

// How booking, ordering or a service works, step by step.
type StepsProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  description?: string | null;
  items?: StepItem[] | null;
  form?: "numbered" | "horizontal" | "connected";
};

type TimelineItem = {
  date: string;
  title: string;
  body?: string | null;
  image?: string | null;
};

// A story over time: history, milestones, an event programme.
type TimelineProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  description?: string | null;
  items?: TimelineItem[] | null;
  form?: "vertical" | "alternating";
};

type TeamMember = {
  name: string;
  role?: string | null;
  bio?: string | null;
  image?: string | null;
};

// The people of a studio, clinic, firm or school.
type TeamProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  description?: string | null;
  items?: TeamMember[] | null;
  form?: "grid" | "list" | "portraits";
};

type PriceGroup = {
  title?: string | null;
  items: PriceItem[];
};

type PriceItem = {
  name: string;
  price?: string | number | null;
  description?: string | null;
  tags?: string[];
};

// A menu or a price list, in groups (breads, pastries; cuts, colour).
type PriceListProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  description?: string | null;
  groups: PriceGroup[];
  form?: "menu" | "columns" | "cards";
};

type OpeningHours = {
  days: string;
  opens?: string | null;
  closes?: string | null;
  note?: string | null;
};

// Where to find a place and when it is open; a link to a map, never an embedded one.
type LocationProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  address: string;
  hours?: OpeningHours[];
  phone?: string | null;
  email?: string | null;
  mapLink?: string | null;
  image?: string | null;
  form?: "split" | "card" | "band";
};

type ComparisonRow = {
  label: string;
  values: (string | boolean)[];
};

// Options side by side: plans, packages, before and after.
type ComparisonProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  description?: string | null;
  columns: string[];
  rows: ComparisonRow[];
  form?: "table" | "cards";
};

// What the business stands for, or one real quote, set large.
type StatementProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  text: string;
  attribution?: string | null;
  image?: string | null;
  form?: "large" | "quote" | "band";
};

type FormProps = {
  title?: string | null;
  description?: string | null;
};

type SectionControls = {
  search?: boolean;
  filters?: string[];
  sort?: string[];
  pageSize?: number | null;
};

type CardGridProps = {
  title?: string | null;
  description?: string | null;
  actions?: SectionAction[];
  controls?: SectionControls | null;
  cardStyle?: "outline" | "filled" | "plain";
  featured?: boolean;
};

// CardGrid, DataTable, DetailView, List: the records come from `data`; content only titles the section.
type DataSectionProps = {
  title?: string | null;
  description?: string | null;
  actions?: SectionAction[];
  controls?: SectionControls | null;
};

type ColumnsProps = {
  title?: string | null;
  columns?: 2 | 3 | 4 | null;
  gap?: "sm" | "md" | "lg";
};

type StackProps = {
  title?: string | null;
  gap?: "sm" | "md" | "lg";
};

type GridProps = {
  title?: string | null;
  columns?: 2 | 3 | 4;
  gap?: "sm" | "md" | "lg";
};

type TabsProps = {
  labels?: string[] | null;
};
