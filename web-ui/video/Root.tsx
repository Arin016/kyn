import React from "react";
import { Composition } from "remotion";
import { ProductDemo, PRODUCT_DEMO_FPS, PRODUCT_DEMO_DURATION, PRODUCT_DEMO_WIDTH, PRODUCT_DEMO_HEIGHT } from "./ProductDemo";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="ProductDemo"
        component={ProductDemo}
        durationInFrames={PRODUCT_DEMO_DURATION}
        fps={PRODUCT_DEMO_FPS}
        width={PRODUCT_DEMO_WIDTH}
        height={PRODUCT_DEMO_HEIGHT}
      />
    </>
  );
};
