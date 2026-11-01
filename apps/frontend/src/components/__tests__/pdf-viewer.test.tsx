import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import PdfViewer from '../pdf-viewer'

const { getPage, getDocument } = vi.hoisted(() => ({ getPage: vi.fn(), getDocument: vi.fn() }))
vi.mock('pdfjs-dist', () => ({
 GlobalWorkerOptions: {},
 getDocument,
}))
vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker' }))

beforeEach(() => {
 getPage.mockReset()
 getDocument.mockReset()
 getDocument.mockImplementation(() => ({ promise: Promise.resolve({ numPages:5, getPage, destroy: vi.fn() }), destroy: vi.fn() }))
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

it('retries a failed document load', async () => {
 getDocument.mockImplementationOnce(() => ({ promise: Promise.reject(new Error('offline')), destroy: vi.fn() }))
 const log = vi.spyOn(console, 'error').mockImplementation(() => {})
 render(<PdfViewer url="/test.pdf" />)
 await screen.findByText(/PDF 加载失败/)
 fireEvent.click(screen.getByRole('button', { name: /重试/ }))
 await screen.findByText(/1\s*\/\s*5 页/)
 expect(getDocument).toHaveBeenCalledTimes(2)
 log.mockRestore()
})

it('clears the previous error and page count when the URL changes', async () => {
 getDocument.mockImplementationOnce(() => ({ promise: Promise.reject(new Error('offline')), destroy: vi.fn() }))
 const log = vi.spyOn(console, 'error').mockImplementation(() => {})
 const { rerender } = render(<PdfViewer url="/first.pdf" />)
 await screen.findByText(/PDF 加载失败/)
 rerender(<PdfViewer url="/second.pdf" />)
 await screen.findByText(/1\s*\/\s*5 页/)
 expect(screen.queryByText(/PDF 加载失败/)).toBeNull()
 log.mockRestore()
})
