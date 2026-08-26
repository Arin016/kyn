import { useEffect, useState } from "react";
import "../video/demo.css";
import { buildSnapshot, cursorPlan } from "../video/demoState";
import { StagedConsole } from "../video/components/StagedConsole";
import { DemoWorkflowPage } from "../video/components/DemoWorkflowPage";
import { buildWorkflowSnapshot, workflowCursorPlan } from "../video/workflowState";
import { DURATION, FPS, scenes, sec } from "../video/timeline";
import {
  DemoBrandCard,
  DemoCamera,
  DemoCaption,
  DemoCursor,
  DemoHighlight,
  easeCamera,
} from "./overlays";
import { interpolate } from "./motion";

function captionFor(frame: number): { text: string; subtext?: string; appearAt: number } | null {
  if (frame >= scenes.selectBot.start && frame < scenes.type.start) {
    return {
      text: "Named agents, not throwaway chats",
      subtext: "Each bot keeps its Kiro session and history.",
      appearAt: scenes.selectBot.start,
    };
  }
  if (frame >= scenes.type.start && frame < scenes.stream.start) {
    return {
      text: "Talk in the control room",
      subtext: "Same ChatGPT-class thread. Local only for Laptop.",
      appearAt: scenes.type.start,
    };
  }
  if (frame >= scenes.stream.start && frame < scenes.workflow.start) {
    return {
      text: "Watch the work stream live",
      subtext: "Reasoning, tools, and the answer in one column.",
      appearAt: scenes.stream.start,
    };
  }
  if (frame >= scenes.workflow.start && frame < scenes.telegram.start) {
    return {
      text: "Compose a team on the canvas",
      subtext: "Parallel bots, explicit arrows, recorded outputs per node.",
      appearAt: scenes.workflow.start,
    };
  }
  if (frame >= scenes.telegram.start && frame < scenes.approve.start) {
    return {
      text: "Phone is a first-class thread",
      subtext: "Telegram lands in Recents. Laptop mirrors — does not impersonate.",
      appearAt: scenes.telegram.start,
    };
  }
  if (frame >= scenes.approve.start && frame < scenes.close.start) {
    return {
      text: "Approvals stay in Inspect",
      subtext: "Allow once or Deny. Never a buried Safety tab.",
      appearAt: scenes.approve.start,
    };
  }
  return null;
}

function cameraFor(frame: number) {
  if (frame < scenes.enter.end) {
    return easeCamera(frame, { scale: 1.12, x: 0, y: 20 }, { scale: 1, x: 0, y: 0 }, scenes.enter.start, scenes.enter.end);
  }
  if (frame < scenes.workflow.start) {
    if (frame < scenes.stream.start + sec(2)) return { scale: 1, x: 0, y: 0 };
    if (frame < scenes.telegram.start) {
      return easeCamera(
        frame,
        { scale: 1, x: 0, y: 0 },
        { scale: 1.12, x: -40, y: -30 },
        scenes.stream.start + sec(2),
        scenes.stream.start + sec(5),
      );
    }
    return { scale: 1.12, x: -40, y: -30 };
  }
  if (frame < scenes.workflow.end) {
    return easeCamera(
      frame,
      { scale: 1, x: 0, y: 0 },
      { scale: 1.14, x: -120, y: -40 },
      scenes.workflow.start,
      scenes.workflow.start + sec(4),
    );
  }
  if (frame < scenes.approve.start) {
    return easeCamera(
      frame,
      { scale: 1.14, x: -120, y: -40 },
      { scale: 1.08, x: 80, y: 10 },
      scenes.telegram.start,
      scenes.telegram.start + sec(3),
    );
  }
  if (frame < scenes.close.start) {
    return easeCamera(
      frame,
      { scale: 1.08, x: 80, y: 10 },
      { scale: 1.18, x: -160, y: -20 },
      scenes.approve.start,
      scenes.approve.start + sec(3),
    );
  }
  return easeCamera(
    frame,
    { scale: 1.18, x: -160, y: -20 },
    { scale: 1, x: 0, y: 0 },
    scenes.close.start,
    scenes.close.start + sec(2),
  );
}

function useDirectorFrame() {
  const [frame, setFrame] = useState(0);
  const driven = new URLSearchParams(location.search).get("drive") === "1";

  useEffect(() => {
    if (driven) {
      const onTick = () => {
        const next = (window as Window & { __DEMO_FRAME__?: number }).__DEMO_FRAME__ ?? 0;
        setFrame(next);
      };
      window.addEventListener("demo-tick", onTick);
      return () => window.removeEventListener("demo-tick", onTick);
    }

    let current = 0;
    const stepMs = 1000 / FPS;
    const id = window.setInterval(() => {
      current += 1;
      setFrame(current);
      if (current >= DURATION) window.clearInterval(id);
    }, stepMs);
    return () => window.clearInterval(id);
  }, [driven]);

  return frame;
}

export function DemoDirector() {
  const frame = useDirectorFrame();

  useEffect(() => {
    document.documentElement.style.margin = "0";
    document.documentElement.style.background = "#0A0A0A";
    document.body.style.margin = "0";
    document.body.style.background = "#0A0A0A";
    document.body.style.overflow = "hidden";
  }, []);

  const inWorkflow = frame >= scenes.workflow.start && frame < scenes.workflow.end;
  const snapshot = buildSnapshot(frame);
  const workflowSnap = buildWorkflowSnapshot(frame);
  const cursorRaw = inWorkflow ? workflowCursorPlan(frame) : cursorPlan(frame);
  const clickAgeFrames =
    cursorRaw.clicking && cursorRaw.clickFrame > 0 ? Math.max(0, frame - cursorRaw.clickFrame) : 0;
  const caption = captionFor(frame);
  const camera = cameraFor(frame);

  const brandOut = interpolate(frame, [scenes.brand.end - sec(1), scenes.enter.end], [1, 0]);
  const showConsole =
    !inWorkflow && frame >= scenes.enter.start && frame < scenes.close.start + sec(1.5);
  const consoleOpacity = interpolate(
    frame,
    [scenes.enter.start, scenes.enter.start + sec(1.2), scenes.close.start, scenes.close.start + sec(1.5)],
    [0, 1, 1, 0],
  );
  const workflowOpacity = interpolate(
    frame,
    [scenes.workflow.start, scenes.workflow.start + sec(0.8), scenes.workflow.end - sec(0.5), scenes.workflow.end],
    [0, 1, 1, 0],
  );

  const highlightTelegram = frame >= scenes.telegram.start && frame < scenes.telegram.start + sec(3.2);
  const highlightInspect = frame >= scenes.approve.start + sec(1) && frame < scenes.approve.start + sec(4);
  const highlightRun =
    inWorkflow && frame >= scenes.workflow.start + sec(8) && frame < scenes.workflow.start + sec(10);

  return (
    <div
      style={{
        width: 1920,
        height: 1080,
        overflow: "hidden",
        background: "#0A0A0A",
        position: "relative",
      }}
      data-demo-frame={frame}
      data-demo-ready={frame >= DURATION - 1 ? "done" : "playing"}
    >
      {frame < scenes.enter.end ? (
        <div style={{ position: "absolute", inset: 0, opacity: brandOut }}>
          <DemoBrandCard mode="intro" frame={frame} localFrame={frame} />
        </div>
      ) : null}

      {showConsole ? (
        <div style={{ position: "absolute", inset: 0, opacity: consoleOpacity }}>
          <DemoCamera scale={camera.scale} x={camera.x} y={camera.y}>
            <div className="demo-stage" style={{ width: 1920, height: 1080, position: "relative" }}>
              <StagedConsole snapshot={snapshot} />
              {highlightTelegram ? (
                <DemoHighlight x={18} y={392} width={236} height={52} label="Recents" />
              ) : null}
              {highlightInspect ? (
                <DemoHighlight x={1588} y={72} width={300} height={920} label="Inspect on demand" />
              ) : null}
              <DemoCursor
                x={cursorRaw.x}
                y={cursorRaw.y}
                clicking={cursorRaw.clicking}
                visible={cursorRaw.visible}
                clickAgeFrames={clickAgeFrames}
                fps={FPS}
              />
            </div>
          </DemoCamera>
          {caption ? (
            <DemoCaption
              text={caption.text}
              subtext={caption.subtext}
              frame={frame}
              appearAt={caption.appearAt}
              fps={FPS}
            />
          ) : null}
        </div>
      ) : null}

      {inWorkflow ? (
        <div style={{ position: "absolute", inset: 0, opacity: workflowOpacity }}>
          <DemoCamera scale={camera.scale} x={camera.x} y={camera.y}>
            <div style={{ width: 1920, height: 1080, position: "relative" }}>
              <DemoWorkflowPage snapshot={workflowSnap} frame={frame} fps={FPS} />
              {highlightRun ? <DemoHighlight x={1640} y={96} width={200} height={44} label="Run workflow" /> : null}
              <DemoCursor
                x={cursorRaw.x}
                y={cursorRaw.y}
                clicking={cursorRaw.clicking}
                visible={cursorRaw.visible}
                clickAgeFrames={clickAgeFrames}
                fps={FPS}
              />
            </div>
          </DemoCamera>
          {caption ? (
            <DemoCaption
              text={caption.text}
              subtext={caption.subtext}
              frame={frame}
              appearAt={caption.appearAt}
              fps={FPS}
            />
          ) : null}
        </div>
      ) : null}

      {frame >= scenes.close.start ? (
        <DemoBrandCard
          mode="outro"
          frame={frame - scenes.close.start}
          localFrame={frame - scenes.close.start}
        />
      ) : null}
    </div>
  );
}
