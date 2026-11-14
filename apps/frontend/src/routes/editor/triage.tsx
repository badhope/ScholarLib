import { useState } from "react";
import {
  createFileRoute,
  Link,
  redirect,
  useNavigate,
} from "@tanstack/react-router";
import { ArrowRight, Clock, Send, Undo2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { getAuthState } from "@/lib/auth";
import { useTriageQueue, useTriageSubmission } from "@/hooks/api/use-modules";
import type { SubmissionResponse } from "@/lib/types";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import {
  EmptyState,
  ErrorState,
  LoadingSkeleton,
} from "@/components/common/state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export const Route = createFileRoute("/editor/triage")({
  beforeLoad: () => {
    const state = getAuthState();
    if (!state.isAuthenticated) throw redirect({ to: "/login" });
    const roles = state.user?.roles ?? [];
    if (
      !state.isAdmin &&
      !roles.some((r) =>
        ["editor", "section_editor", "editor_in_chief"].includes(r),
      )
    ) {
      throw redirect({ to: "/403" });
    }
  },
  component: TriagePage,
});

type Action = "return_for_revision" | "desk_reject";

function ageLabel(iso: string): string {
  const hours = Math.max(0, (Date.now() - new Date(iso).getTime()) / 3_600_000);
  if (hours < 24) return `${Math.floor(hours)} 小时`;
  return `${Math.floor(hours / 24)} 天`;
}

function TriagePage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const { data, isLoading, isError, refetch } = useTriageQueue(page, 20);
  const triage = useTriageSubmission();
  const [dialog, setDialog] = useState<{
    item: SubmissionResponse;
    action: Action;
  } | null>(null);
  const [note, setNote] = useState("");

  const items = data?.data ?? [];
  const total = data?.meta.total ?? 0;

  function sendToReview(item: SubmissionResponse) {
    triage.mutate(
      { id: item.id, decision: "send_to_review", note: "初筛通过，送同行评审" },
      {
        onSuccess: () => {
          toast.success("已标记送外审，请到待指派队列分派审稿人");
          navigate({ to: "/submissions/pending" });
        },
      },
    );
  }

  function openDialog(item: SubmissionResponse, action: Action) {
    setDialog({ item, action });
    setNote("");
  }

  function submitDialog() {
    if (!dialog) return;
    if (note.trim().length < 10) {
      toast.error("请写至少 10 字理由，作者需要知道下一步怎么做");
      return;
    }
    triage.mutate(
      { id: dialog.item.id, decision: dialog.action, note: note.trim() },
      {
        onSuccess: () => {
          toast.success(
            dialog.action === "return_for_revision"
              ? "已退回修改"
              : "已直接拒稿",
          );
          setDialog(null);
        },
      },
    );
  }

  return (
    <div>
      <PageHeader
        title="初筛队列"
        description="两段式评审的第一段：先判断选题、格式与范围，再决定送外审、退回修改或直接拒稿。"
        actions={
          <Link to="/submissions/pending">
            <Button variant="outline" size="sm">
              待指派队列
              <ArrowRight className="ml-1 h-4 w-4" aria-hidden />
            </Button>
          </Link>
        }
      />

      <div className="mb-4 rounded-md border border-dashed bg-muted/30 p-3 text-xs leading-relaxed text-muted-foreground">
        <span className="font-medium text-foreground">初筛口径：</span>
        只做“是否值得进入同行评审”的判断，不替代审稿意见。退回修改和直接拒稿必须写清理由；
        送外审后仍要到「待指派」里选择审稿人，系统会自动记录初筛通过。
      </div>

      {isLoading ? (
        <LoadingSkeleton rows={4} />
      ) : isError ? (
        <ErrorState message="初筛队列加载失败" onRetry={() => refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          title="初筛队列已清空"
          description="新投稿会先到这里；已完成初筛的稿件在「待指派」继续处理。"
        />
      ) : (
        <>
          <div className="mb-3 flex items-center justify-between text-sm text-muted-foreground">
            <span>共 {total} 篇待初筛 · 最老的排在最前</span>
            <div className="flex items-center gap-2">
              <Badge variant="outline">
                <Clock className="mr-1 h-3 w-3" aria-hidden />
                按投稿时间
              </Badge>
              <span className="text-xs text-muted-foreground">
                超过 48 小时标红
              </span>
            </div>
          </div>
          <div className="space-y-3">
            {items.map((item) => {
              const overdue =
                Date.now() - new Date(item.submitted_at).getTime() >=
                48 * 3_600_000;
              return (
                <Card key={item.id}>
                  <CardContent className="space-y-3 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <h2 className="font-medium">{item.title}</h2>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <Badge variant="outline">{item.type}</Badge>
                          <span>{item.discipline}</span>
                          <span>·</span>
                          <span className="truncate">
                            {item.authors.join("、")}
                          </span>
                          <span>·</span>
                          <span>投稿 {ageLabel(item.submitted_at)}前</span>
                          {overdue ? (
                            <Badge variant="destructive">超 48 小时</Badge>
                          ) : null}
                        </div>
                      </div>
                      {typeof item.similarity_score === "number" &&
                      item.similarity_score >= 35 ? (
                        <Badge variant="outline">
                          站内相似度 {Math.round(item.similarity_score)}
                        </Badge>
                      ) : null}
                    </div>
                    <p className="line-clamp-3 text-sm text-muted-foreground">
                      {item.abstract}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        onClick={() => sendToReview(item)}
                        disabled={triage.isPending}
                      >
                        <Send className="mr-1 h-4 w-4" aria-hidden />
                        送外审
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => openDialog(item, "return_for_revision")}
                        disabled={triage.isPending}
                      >
                        <Undo2 className="mr-1 h-4 w-4" aria-hidden />
                        退回修改
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => openDialog(item, "desk_reject")}
                        disabled={triage.isPending}
                      >
                        <XCircle className="mr-1 h-4 w-4" aria-hidden />
                        直接拒稿
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
          {(data?.meta.total_pages ?? 1) > 1 ? (
            <Pagination
              page={page}
              totalPages={data?.meta.total_pages ?? 1}
              onPageChange={setPage}
            />
          ) : null}
        </>
      )}

      <Dialog
        open={dialog !== null}
        onOpenChange={(open) => !open && setDialog(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialog?.action === "return_for_revision"
                ? "退回修改"
                : "直接拒稿"}{" "}
              — {dialog?.item.title}
            </DialogTitle>
            <DialogDescription>
              {dialog?.action === "return_for_revision"
                ? "稿件会进入 major_revision，作者可修改后重投；请写清必须改什么。"
                : "稿件直接进入 rejected，不进入同行评审；请写清范围/格式/规范上的硬性原因。"}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="triage-note">编辑部说明（至少 10 字）</Label>
            <Textarea
              id="triage-note"
              rows={5}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="例如：图表编号与正文不一致，参考文献缺卷期页码；请按投稿模板重排后再投。"
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialog(null)}>
              取消
            </Button>
            <Button
              onClick={submitDialog}
              disabled={triage.isPending}
              variant={
                dialog?.action === "desk_reject" ? "destructive" : "default"
              }
            >
              {triage.isPending ? "提交中…" : "确认"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
