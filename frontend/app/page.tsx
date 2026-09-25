"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getStoredToken } from "../lib/api";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    const token = getStoredToken();
    if (token) {
      router.push("/chat");
    } else {
      router.push("/login");
    }
  }, [router]);

  return (
    <div className="flex h-screen items-center justify-center bg-slate-950">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
    </div>
  );
}
