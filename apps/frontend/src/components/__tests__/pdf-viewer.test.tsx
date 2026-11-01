import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import PdfViewer from '../pdf-viewer'

const { getPage } = vi.hoisted(() => ({ getPage: vi.fn() }))
vi.mock('pdfjs-dist', () => ({
 GlobalWorkerOptions: {},
 getDocument: () => ({ promise: Promise.resolve({ numPages:5, getPage, destroy: vi.fn() }) }),
}))
vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker' }))

beforeEach(() => {
 getPage.mockReset()
 getPage.mockImplementation(async () => ({
 getViewport: () => ({ width:100, height:100 }),
 render: () => ({ promise: Promise.resolve() }),
 }))
 vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ clearRect: vi.fn() } as unknown as CanvasRenderingContext2D)
})

it('renders externally selected pages and reports progress using the latest callback', async () => {
 const first = vi.fn()
 const latest = vi.fn()
 const { rerender } = render(<PdfViewer url="/test.pdf" initialPage={2} onPageChange={first} />)
 await waitFor(() => expect(first).toHaveBeenCalledWith(2))
 rerender(<PdfViewer url="/test.pdf" initialPage={4} onPageChange={latest} />)
 await waitFor(() => expect(getPage).toHaveBeenCalledWith(4))
 await waitFor(() => expect(latest).toHaveBeenCalledWith(4))
 expect(screen.getByText(/4\s*\/\s*5 页/)).toBeTruthy()
})
