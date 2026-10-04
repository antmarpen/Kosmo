import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { MarkdownPreview } from "./MarkdownPreview";

/**
 * Read-only Markdown viewer in the shared Radix dialog (WP-12 contract for
 * "view instructions" surfaces). The dialog owns the standard focus contract:
 * the shared close X takes initial focus and focus returns to the opener on
 * close. All user-facing text arrives through props so consuming features
 * pass localized values; the empty state is owned by `MarkdownPreview`.
 */
export function MarkdownPreviewDialog({
  open,
  onOpenChange,
  title,
  source,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  source: string;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-y-auto pr-1">
          <MarkdownPreview source={source} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
