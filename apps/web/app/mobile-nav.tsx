import Link from "next/link";

export function MobileNav() {
  return (
    <nav className="mobile-nav" aria-label="移动端主导航">
      <Link href="/mobile">状态</Link>
      <Link href="/mobile#machines">机器</Link>
      <Link href="/mobile#events">事件</Link>
    </nav>
  );
}
