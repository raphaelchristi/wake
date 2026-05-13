import { redirect } from "next/navigation";

/**
 * The root path is just a router: send operators to the sessions list. The
 * authed group layout will redirect them to /login if they don't have a key.
 */
export default function RootPage(): never {
  redirect("/sessions");
}
