import React from "react";
import Link from "next/link";
import { StateView } from "../../ui/primitives";

export default function OperationNotFound() {
  return <main><Link className="back" href="/operations">← 操作列表</Link>
    <StateView state="unavailable" title="操作不存在" description="控制平面没有此 Operation 记录，请核对链接。" />
  </main>;
}
