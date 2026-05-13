import type { Meta, StoryObj } from "@storybook/react";
import { ReplayScrubber } from "@/components/replay/ReplayScrubber";
import fixture from "../../tests/fixtures/events-fixture.json";
import type { WakeEvent } from "@/lib/replay/types";

const events = (fixture as unknown as { data: WakeEvent[] }).data;

const meta: Meta<typeof ReplayScrubber> = {
  title: "Replay/ReplayScrubber",
  component: ReplayScrubber,
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof ReplayScrubber>;

export const Default: Story = {
  args: {
    events,
    bindKeyboard: false,
  },
};

export const Empty: Story = {
  args: {
    events: [],
    bindKeyboard: false,
  },
};

export const Single: Story = {
  args: {
    events: events.slice(0, 1),
    bindKeyboard: false,
  },
};

export const HundredEvents: Story = {
  args: {
    events: Array.from({ length: 100 }, (_, i) => ({
      ...(events[i % events.length] as WakeEvent),
      id: `gen_${i}`,
      seq: i,
    })),
    bindKeyboard: false,
  },
};

export const ThousandEvents: Story = {
  // Performance probe — should still be smooth.
  args: {
    events: Array.from({ length: 1000 }, (_, i) => ({
      ...(events[i % events.length] as WakeEvent),
      id: `gen_${i}`,
      seq: i,
    })),
    bindKeyboard: false,
  },
};
