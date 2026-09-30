import { StateView } from "@/app/ui/primitives";
export default function Loading() {
  return <main><StateView state="loading" title="正在读取操作" description="等待控制平面的计划、状态与审计记录。" /></main>;
}
