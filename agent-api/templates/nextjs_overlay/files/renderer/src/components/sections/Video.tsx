import { VideoEmbed } from "@/components/assets/VideoEmbed";
import { Grid } from "@/components/layout/Grid";
import { Section } from "@/components/layout/Section";
import { backdropImage } from "./AssetImage";
import type { TVideoContent } from "./types";

type VideoProps = TVideoContent;

/** Epic 31 (Story 31.3): one featured video with a heading and a short text, or a grid of two to six videos with
 *  their titles. Each video is a `VideoEmbed` (a YouTube facade that loads the player on play, or a Pixabay file in
 *  our own player), credited under it. */
export function Video(props: VideoProps) {
  const { title, description, video, items = [], columns = 2, background, backgroundImage } = props;
  const listed = items.filter((item) => item.video);
  return (
    <Section title={title} description={description} background={background} backdrop={backdropImage(backgroundImage)}>
      {video && (
        <div className="mx-auto w-full max-w-4xl" data-motion-part="media">
          <VideoEmbed asset={video} />
        </div>
      )}
      {listed.length > 0 && (
        <Grid columns={listed.length === 1 ? 2 : columns}>
          {listed.map((item) => (
            <figure key={item.video + (item.title ?? "")} className="flex flex-col gap-3" data-motion-part="media">
              <VideoEmbed asset={item.video} compact />
              {(item.title || item.caption) && (
                <figcaption className="flex flex-col gap-1">
                  {item.title && <span className="font-medium">{item.title}</span>}
                  {item.caption && <span className="text-sm text-muted-foreground">{item.caption}</span>}
                </figcaption>
              )}
            </figure>
          ))}
        </Grid>
      )}
    </Section>
  );
}
