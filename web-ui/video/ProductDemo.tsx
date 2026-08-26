import React from "react";
import {
  AbsoluteFill,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import "@fontsource-variable/inter";
import "@fontsource-variable/space-grotesk";
import "../src/styles/global.css";
import "./demo.css";
import { Camera, easeCamera } from "./components/Camera";
import { Caption } from "./components/Caption";
import { Cursor } from "./components/Cursor";
import { DemoWorkflowPage } from "./components/DemoWorkflowPage";
import { Highlight } from "./components/Highlight";
import { StagedConsole } from "./components/StagedConsole";
import { BrandCard } from "./scenes/BrandCard";
import { buildSnapshot, cursorPlan } from "./demoState";
import { buildWorkflowSnapshot } from "./workflowState";
import {
  DURATION,
  FPS,
  HEIGHT,
  WIDTH,
  scenes,
  sec,
} from "./timeline";

export const PRODUCT_DEMO_FPS = FPS;
export const PRODUCT_DEMO_DURATION = DURATION;
export const PRODUCT_DEMO_WIDTH = WIDTH;
export const PRODUCT_DEMO_HEIGHT = HEIGHT;

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
    return easeCamera(
      frame,
      { scale: 1, x: 0, y: 0 },
      { scale: 1.12, x: -40, y: -30 },
      scenes.stream.start + sec(2),
      scenes.stream.start + sec(5),
    );
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

export const ProductDemo: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inWorkflow = frame >= scenes.workflow.start && frame < scenes.workflow.end;
  const snapshot = buildSnapshot(frame);
  const workflowSnap = buildWorkflowSnapshot(frame);
  const cursor = cursorPlan(frame);
  const caption = captionFor(frame);
  const camera = cameraFor(frame);

  const brandOut = interpolate(frame, [scenes.brand.end - sec(1), scenes.enter.end], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const consoleIn = spring({
    frame: Math.max(0, frame - scenes.enter.start),
    fps,
    config: { damping: 18, stiffness: 80 },
  });

  const showConsole = !inWorkflow && frame >= scenes.enter.start && frame < scenes.close.start + sec(1.5);
  const consoleOpacity = interpolate(
    frame,
    [scenes.enter.start, scenes.enter.start + sec(1.2), scenes.close.start, scenes.close.start + sec(1.5)],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const workflowOpacity = interpolate(
    frame,
    [scenes.workflow.start, scenes.workflow.start + sec(0.8), scenes.workflow.end - sec(0.5), scenes.workflow.end],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const highlightTelegram = frame >= scenes.telegram.start && frame < scenes.telegram.start + sec(3.2);
  const highlightInspect = frame >= scenes.approve.start + sec(1) && frame < scenes.approve.start + sec(4);
  const highlightRun =
    inWorkflow && frame >= scenes.workflow.start + sec(8) && frame < scenes.workflow.start + sec(10);

  return (
    <AbsoluteFill style={{ background: "#0A0A0A" }}>
      <Sequence from={0} durationInFrames={scenes.enter.end} name="BrandIntro" layout="none">
        <AbsoluteFill style={{ opacity: brandOut }}>
          <BrandCard mode="intro" />
        </AbsoluteFill>
      </Sequence>

      {showConsole ? (
        <AbsoluteFill style={{ opacity: consoleOpacity * Math.min(1, consoleIn + 0.2) }}>
          <Camera scale={camera.scale} x={camera.x} y={camera.y}>
            <AbsoluteFill className="demo-stage">
              <StagedConsole snapshot={snapshot} />
              {highlightTelegram ? (
                <Highlight x={18} y={392} width={236} height={52} active label="Recents" />
              ) : null}
              {highlightInspect ? (
                <Highlight x={1588} y={72} width={300} height={920} active label="Inspect on demand" />
              ) : null}
              <Cursor
                x={cursor.x}
                y={cursor.y}
                clicking={cursor.clicking}
                visible={cursor.visible}
                clickFrame={cursor.clickFrame}
              />
            </AbsoluteFill>
          </Camera>
          {caption ? (
            <Caption text={caption.text} subtext={caption.subtext} active appearAt={caption.appearAt} />
          ) : null}
        </AbsoluteFill>
      ) : null}

      {inWorkflow ? (
        <AbsoluteFill style={{ opacity: workflowOpacity }}>
          <Camera scale={camera.scale} x={camera.x} y={camera.y}>
            <AbsoluteFill style={{ width: WIDTH, height: HEIGHT }}>
              <DemoWorkflowPage snapshot={workflowSnap} frame={frame} fps={fps} />
              {highlightRun ? (
                <Highlight x={1640} y={96} width={200} height={44} active label="Run workflow" />
              ) : null}
              <Cursor
                x={cursor.x}
                y={cursor.y}
                clicking={cursor.clicking}
                visible={cursor.visible}
                clickFrame={cursor.clickFrame}
              />
            </AbsoluteFill>
          </Camera>
          {caption ? (
            <Caption text={caption.text} subtext={caption.subtext} active appearAt={caption.appearAt} />
          ) : null}
        </AbsoluteFill>
      ) : null}

      <Sequence from={scenes.close.start} durationInFrames={DURATION - scenes.close.start} name="Outro" layout="none">
        <BrandCard mode="outro" />
      </Sequence>
    </AbsoluteFill>
  );
};

export default ProductDemo;
