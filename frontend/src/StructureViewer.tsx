import { useEffect, useRef } from "react";

type Viewer = {
  addModel: (data: string, format: string) => void;
  setStyle: (sel: object, style: object) => void;
  addStyle: (sel: object, style: object) => void;
  zoomTo: (sel?: object) => void;
  render: () => void;
  clear: () => void;
};

type ViewerHandle = Viewer & {
  divwatcher?: { disconnect: () => void };
  intwatcher?: { disconnect: () => void };
};

type MolNS = {
  createViewer: (element: HTMLElement, config?: object) => Viewer;
};

function paint(
  viewer: Viewer,
  triad: number[],
  activity: number[],
  stability: number[],
) {
  viewer.setStyle({}, { cartoon: { color: "#7a8b99", opacity: 0.95 } });
  if (stability.length) {
    viewer.addStyle(
      { resi: stability, chain: "A" },
      { cartoon: { color: "#2563eb" }, stick: { color: "#2563eb", radius: 0.12 } },
    );
  }
  if (activity.length) {
    viewer.addStyle(
      { resi: activity, chain: "A" },
      { cartoon: { color: "#0d9488" }, stick: { color: "#0d9488", radius: 0.14 } },
    );
  }
  if (triad.length) {
    viewer.addStyle(
      { resi: triad, chain: "A" },
      { cartoon: { color: "#be123c" }, stick: { color: "#be123c", radius: 0.2 } },
    );
  }
}

function frame(viewer: Viewer, focus: number | null, triad: number[]) {
  const target = focus ?? triad[0];
  if (target) viewer.zoomTo({ resi: target, chain: "A" });
  else viewer.zoomTo();
}

export function StructureViewer({
  pdbText,
  triad,
  activity,
  stability,
  focus,
}: {
  pdbText: string;
  triad: number[];
  activity: number[];
  stability: number[];
  focus: number | null;
}) {
  const host = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<ViewerHandle | null>(null);
  const marks = useRef({ triad, activity, stability, focus });
  marks.current = { triad, activity, stability, focus };
  const triadKey = triad.join(",");
  const activityKey = activity.join(",");
  const stabilityKey = stability.join(",");

  useEffect(() => {
    const element = host.current;
    if (!element || !pdbText) return;
    let cancelled = false;

    void import("3dmol/build/3Dmol.es6.js").then((mod) => {
      if (cancelled || !host.current) return;
      const $3Dmol = ((mod as { default?: MolNS }).default ?? mod) as MolNS;
      const viewer = $3Dmol.createViewer(host.current, {
        backgroundColor: "#e8eef4",
        antialias: true,
      }) as ViewerHandle;
      viewer.divwatcher?.disconnect();
      viewer.intwatcher?.disconnect();
      viewer.addModel(pdbText, "pdb");
      paint(viewer, marks.current.triad, marks.current.activity, marks.current.stability);
      frame(viewer, marks.current.focus, marks.current.triad);
      viewer.render();
      viewerRef.current = viewer;
    });

    return () => {
      cancelled = true;
      const viewer = viewerRef.current;
      viewer?.divwatcher?.disconnect();
      viewer?.intwatcher?.disconnect();
      viewer?.clear();
      viewerRef.current = null;
      element.replaceChildren();
    };
  }, [pdbText]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    paint(viewer, marks.current.triad, marks.current.activity, marks.current.stability);
    viewer.render();
  }, [triadKey, activityKey, stabilityKey]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || focus == null) return;
    viewer.zoomTo({ resi: focus, chain: "A" });
    viewer.render();
  }, [focus]);

  return <div className="viewer" ref={host} />;
}
