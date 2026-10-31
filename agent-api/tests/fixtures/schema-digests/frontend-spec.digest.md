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
  auth?: Record<string, unknown> | null;
  x-backendSpec?: string | null;
};

// An image the site shows (Story 15.1).
type Asset = {
  id: string;
  kind?: "image" | "icon" | "video" | "file" | "illustration" | "pattern" | "logo";
  alt?: string | null;
  source?: string;
  prompt?: string | null;
  style?: string | null;
  aspectRatio?: "16:9" | "4:3" | "1:1" | "3:4" | "21:9" | null;
  decorative?: boolean;
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
};

type Header = {
  logoText?: string | null;
  logo?: string | null;
  navigation?: NavLink[];
};

type Layout = {
  shell?: "header-footer" | "sidebar" | "blank";
  header?: Header;
  footer?: Footer;
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
  sections: Section[];
};

type Project = {
  name: string;
  description?: string | null;
  mode: "static" | "dynamic";
  locale?: string;
  locales?: string[];
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
};

type Typography = {
  headingFont?: string | null;
  bodyFont?: string | null;
  scale?: "compact" | "default" | "large";
};

type Cta = {
  label: string;
  page?: string | null;
  href?: string | null;
};

type HeroProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  variant?: "split" | "centered" | "banner";
  heading: string;
  eyebrow?: string | null;
  body?: string | null;
  image?: string | null;
  cta?: Cta | null;
  secondaryCta?: Cta | null;
};

type FeatureItem = {
  title: string;
  body?: string | null;
};

type FeaturesProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  description?: string | null;
  items?: FeatureItem[] | null;
  columns?: 2 | 3 | 4 | null;
  cardStyle?: "outline" | "filled" | "plain";
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
};

type PricingProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  description?: string | null;
  items?: PlanItem[] | null;
  cardStyle?: "outline" | "filled" | "plain";
};

type StatItem = {
  label: string;
  value: string | number;
};

type StatsProps = {
  background?: "default" | "muted" | "primary" | "image";
  backgroundImage?: string | null;
  title?: string | null;
  items?: StatItem[] | null;
  cardStyle?: "outline" | "filled" | "plain";
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

type FormProps = {
  title?: string | null;
  description?: string | null;
};

type CardGridProps = {
  title?: string | null;
  description?: string | null;
  cardStyle?: "outline" | "filled" | "plain";
};

// CardGrid, DataTable, DetailView, List: the records come from `data`; content only titles the section.
type DataSectionProps = {
  title?: string | null;
  description?: string | null;
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
