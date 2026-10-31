import { useEffect, useState } from "react";
import { useSectionRecords } from "@/components/renderer/use-section-records";
import type { TBinding, TRecord } from "@/components/renderer/site";

export default function FlashcardStudy(props: { items?: TRecord[]; binding?: TBinding }) {
  const { records } = useSectionRecords(props.items, props.binding);
  const [queue, setQueue] = useState<number[]>([]);

  useEffect(() => {
    setQueue(records.map((_, i) => i));
  }, [records]);

  return (
    <div className="p-4">
      <p>Queue length: {queue.length}</p>
    </div>
  );
}
