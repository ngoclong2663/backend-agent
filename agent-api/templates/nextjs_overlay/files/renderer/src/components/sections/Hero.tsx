import type { ReactNode } from "react";
import { Container } from "@/components/layout/Container";
import { Backdrop, surfaceClass } from "@/components/layout/Section";
import { cn } from "@/lib/utils";
import { BackgroundVideo } from "@/components/assets/BackgroundVideo";
import { AssetImage } from "./AssetImage";
import { CtaLink } from "./CtaLink";
import { displayClass, headlineClass } from "./styles";
import type { THeroContent } from "./types";

type HeroProps = THeroContent;

type TextProps = Pick<HeroProps, "eyebrow" | "body" | "cta" | "secondaryCta"> & {
  heading: string;
  headline?: string;
  centered?: boolean;
  wide?: boolean;
  eyebrowClassName?: string;
};

/** Eyebrow, headline, text and actions: the same block in every layout, sized and aligned by the layout. */
function HeroText(props: TextProps) {
  const { eyebrow, heading, headline, body, cta, secondaryCta, centered = false, wide = false } = props;
  return (
    <div className={cn("flex flex-col gap-5", centered && "items-center text-center", wide ? "w-full" : "max-w-2xl")}>
      {eyebrow && (
        <p data-motion-part="heading" className={cn("text-sm font-medium text-primary", props.eyebrowClassName)}>
          {eyebrow}
        </p>
      )}
      <h1 data-motion-part="heading" className={cn("heading text-balance", headline ?? headlineClass(heading))}>
        {heading}
      </h1>
      {body && (
        <p data-motion-part="text" className="max-w-prose text-lg text-muted-foreground">
          {body}
        </p>
      )}
      {(cta || secondaryCta) && (
        <div data-motion-part="action" className={cn("flex flex-wrap gap-3", centered && "justify-center")}>
          {cta && <CtaLink cta={cta} />}
          {secondaryCta && <CtaLink cta={secondaryCta} variant="outline" />}
        </div>
      )}
    </div>
  );
}

function Band({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cn("py-16 sm:py-24", className)}>{children}</section>;
}

/**
 * The page opener, in eight layouts (Stories 17.7, 20.2):
 * - `split`: text beside the image from 1024 px (image below on smaller screens);
 * - `centered`: one sentence in wide space, image below;
 * - `banner`: full width; the image fills the band behind the text, or the band takes the primary colour;
 * - `stage`: the image is the first screen, the text set on its lower edge;
 * - `type`: the headline is the image: oversized type across the width, no picture;
 * - `stacked`: a full-width headline, text and actions in a row under it, then a wide image;
 * - `collage`: text beside a grid of two to four images, half and half like `split` (`image` + `images`; fewer
 *   than two → `split`);
 * - `vertical`: the eyebrow as a rotated label beside the headline, at the headline's size (horizontal on phones).
 * The headline stays the first heading and the CTA comes before any image in the DOM, so reading order and the
 * "CTA above the fold" rule hold in every layout.
 */
export function Hero(props: HeroProps) {
  const { variant = "split", background = "default", backgroundImage, backgroundVideo, image, images } = props;
  const collage = [image, ...(images ?? [])].filter((item, index, all): item is string => !!item && all.indexOf(item) === index);
  // Epic 31 (Story 31.3): a background clip wants text over media: the banner (or stage) layout
  const layout = variant === "collage" && collage.length < 2 ? "split" : backgroundVideo && variant !== "stage" ? "banner" : variant;

  if (layout === "banner" || layout === "stage") {
    const stage = layout === "stage";
    const backdrop = image ?? (background === "image" ? backgroundImage : undefined);
    const surface = backdrop || backgroundVideo ? "image" : background === "default" ? "primary" : background;
    return (
      <section
        className={cn(
          stage ? "flex min-h-[min(85svh,820px)] items-end pt-32 pb-12 sm:pb-16" : "py-24 sm:py-32",
          surfaceClass(surface),
        )}
        data-bga-hero-video={backgroundVideo ? "" : undefined}
      >
        {backgroundVideo ? (
          <Backdrop
            className={
              stage
                ? "bg-linear-to-t from-background via-background/70 to-background/10"
                : "bg-linear-to-r from-background via-background/75 to-background/30"
            }
          >
            <BackgroundVideo asset={backgroundVideo} />
          </Backdrop>
        ) : backdrop && (
          <Backdrop
            className={
              stage
                ? "bg-linear-to-t from-background via-background/80 to-background/0"
                : "bg-linear-to-r from-background via-background/85 to-background/40"
            }
          >
            <AssetImage asset={backdrop} className="aspect-auto h-full rounded-none" priority />
          </Backdrop>
        )}
        <Container>
          <HeroText {...props} />
        </Container>
      </section>
    );
  }

  const surface = background === "image" && backgroundImage ? "image" : background;
  const backdrop =
    surface === "image" && backgroundImage ? (
      <Backdrop>
        <AssetImage asset={backgroundImage} className="aspect-auto h-full rounded-none" />
      </Backdrop>
    ) : null;

  if (layout === "type") {
    return (
      <Band className={cn("py-20 sm:py-32", surfaceClass(surface))}>
        {backdrop}
        <Container>
          <HeroText {...props} headline={displayClass(props.heading)} wide />
        </Container>
      </Band>
    );
  }

  if (layout === "stacked") {
    return (
      <Band className={surfaceClass(surface)}>
        {backdrop}
        <Container className="flex flex-col gap-10">
          <h1 data-motion-part="heading" className={cn("heading text-balance", headlineClass(props.heading))}>
            {props.heading}
          </h1>
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div data-motion-part="text" className="flex flex-col gap-3">
              {props.eyebrow && <p className="text-sm font-medium text-primary">{props.eyebrow}</p>}
              {props.body && <p className="max-w-prose text-lg text-muted-foreground">{props.body}</p>}
            </div>
            {(props.cta || props.secondaryCta) && (
              <div data-motion-part="action" className="flex flex-wrap gap-3">
                {props.cta && <CtaLink cta={props.cta} />}
                {props.secondaryCta && <CtaLink cta={props.secondaryCta} variant="outline" />}
              </div>
            )}
          </div>
          {image && <AssetImage asset={image} className="aspect-[21/9]" priority />}
        </Container>
      </Band>
    );
  }

  if (layout === "collage") {
    const shown = collage.slice(0, 4);
    return (
      <Band className={surfaceClass(surface)}>
        {backdrop}
        <Container className="flex flex-col gap-10 lg:grid lg:grid-cols-2 lg:items-center">
          <HeroText {...props} />
          <div className="grid grid-cols-2 gap-3 sm:gap-4">
            {shown.map((asset, index) => (
              <AssetImage
                key={asset}
                asset={asset}
                priority={index === 0}
                className={cn(
                  "aspect-square",
                  index === 0 && shown.length !== 2 && "row-span-2 aspect-auto h-full",
                  index === 3 && "col-span-2 aspect-[2/1]",
                )}
              />
            ))}
          </div>
        </Container>
      </Band>
    );
  }

  if (layout === "vertical") {
    return (
      <Band className={surfaceClass(surface)}>
        {backdrop}
        <Container className="flex flex-col gap-10">
          <div className="flex gap-6 sm:gap-10">
            {props.eyebrow && (
              <p
                data-motion-part="heading"
                className={cn(
                  "hidden shrink-0 rotate-180 font-semibold tracking-[0.2em] text-primary uppercase [writing-mode:vertical-rl] sm:block",
                  headlineClass(props.heading),
                )}
              >
                {props.eyebrow}
              </p>
            )}
            <HeroText {...props} eyebrowClassName={props.eyebrow ? "sm:hidden" : undefined} />
          </div>
          {image && <AssetImage asset={image} className="max-w-4xl" priority />}
        </Container>
      </Band>
    );
  }

  const centered = layout === "centered";
  return (
    <Band className={surfaceClass(surface)}>
      {backdrop}
      <Container
        className={cn(
          "flex flex-col gap-10",
          centered && "items-center text-center",
          image && !centered && "lg:grid lg:grid-cols-2 lg:items-center",
        )}
      >
        <HeroText {...props} centered={centered} />
        {image && <AssetImage asset={image} className={centered ? "max-w-4xl" : undefined} priority />}
      </Container>
    </Band>
  );
}
