import type { Meta, StoryObj } from "@storybook/react";
import { EventDetail } from "@/components/replay/EventDetail";
import fixture from "../../tests/fixtures/events-fixture.json";
import type { WakeEvent } from "@/lib/replay/types";

const events = (fixture as { data: WakeEvent[] }).data;

const meta: Meta<typeof EventDetail> = {
  title: "Replay/EventDetail",
  component: EventDetail,
  parameters: { layout: "fullscreen" },
};
export default meta;
type Story = StoryObj<typeof EventDetail>;

export const UserMessage: Story = { args: { event: events[0] } };
export const ToolUse: Story = {
  args: { event: events.find((e) => e.type === "tool_use") ?? events[0] },
};
export const ToolResult: Story = {
  args: { event: events.find((e) => e.type === "tool_result") ?? events[0] },
};
export const ToolError: Story = {
  args: {
    event:
      events.find(
        (e) => e.type === "tool_result" && (e.payload as { is_error?: boolean }).is_error,
      ) ?? events[0],
  },
};
export const Empty: Story = { args: { event: null } };
