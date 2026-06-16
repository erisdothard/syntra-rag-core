"use client";

import dynamic from "next/dynamic";

const ChatView = dynamic(() => import("@/components/ChatView"), {
  ssr: false,
});

export default function Home() {
  return <ChatView />;
}
