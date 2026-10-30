import type {
  RetrievalWeightReportResponse,
  RetrievalWeightUnitResponse,
} from '@dify/contracts/api/console/apps/types.gen'
import type { consoleClient } from '@/service/console'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWorkflowComponent } from '@/app/components/workflow/__tests__/workflow-test-env'
import { createTestQueryClient } from '@/test/query-client'
import RetrievalTuning from '../retrieval-tuning'

const { getReport } = vi.hoisted(() => ({
  getReport: vi.fn<typeof consoleClient.apps.byAppId.retrievalWeightRecommendations.get>(),
}))
vi.mock('@/service/console', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/service/console')>()
  const { withConsoleResponses } = await import('@/test/console/service-responses')
  return {
    ...actual,
    consoleQuery: withConsoleResponses(actual.consoleQuery, {
      'apps.byAppId.retrievalWeightRecommendations.get': getReport,
    }),
  }
})

const key = (name: string) => `workflow.nodes.knowledgeRetrieval.retrievalTuning.${name}`

const createUnit = (
  overrides: Partial<RetrievalWeightUnitResponse> = {},
): RetrievalWeightUnitResponse => ({
  node_id: 'knowledge-1',
  stage: 'cross_dataset',
  dataset_id: null,
  embedding_provider_name: 'provider',
  embedding_model_name: 'embedding',
  current_vector_weight: 0.7,
  weights_changed_in_window: false,
  verdict: 'recommend_change',
  recommended_vector_weight: 0.5,
  liked_runs: 40,
  disliked_runs: 35,
  required_per_rating: null,
  analysis: {
    best_vector_weight: 0.5,
    improvement: 0.2,
    interval_low: 0.05,
    interval_high: 0.31,
    stability: 0.8,
    affected_share: 0.25,
    curve: [{ vector_weight: 0.5, improvement: 0.2 }],
  },
  ...overrides,
})

const createReport = (
  overrides: Partial<RetrievalWeightReportResponse> = {},
): RetrievalWeightReportResponse => ({
  app_id: 'app-1',
  tracing_enabled: true,
  window_start: 1_790_000_000,
  rated_runs: 75,
  units: [],
  ...overrides,
})

const renderTuning = (
  resource = { kind: 'app' as const, appId: 'app-1', mode: 'advanced-chat' as const },
) =>
  renderWorkflowComponent(
    <RetrievalTuning nodeId="knowledge-1" datasets={[{ id: 'dataset-1', name: 'Product docs' }]} />,
    { queryClient: createTestQueryClient(), resource },
  )

const openSection = async () => {
  await userEvent.setup().click(screen.getByRole('button', { name: key('title') }))
}

describe('RetrievalTuning', () => {
  beforeEach(() => {
    getReport.mockReset()
  })

  it('stays hidden outside app editors', () => {
    renderTuning({ kind: 'knowledge-pipeline', pipelineId: 'pipeline-1' } as never)

    expect(screen.queryByRole('button', { name: key('title') })).not.toBeInTheDocument()
  })

  it('does not request the report until the section is opened', async () => {
    getReport.mockResolvedValue(createReport())
    renderTuning()

    expect(getReport).not.toHaveBeenCalled()

    await openSection()

    expect(await screen.findByText(key('empty'))).toBeInTheDocument()
    expect(getReport).toHaveBeenCalledTimes(1)
  })

  it("shows this node's verdicts with dataset names and the advisory note", async () => {
    getReport.mockResolvedValue(
      createReport({
        units: [
          createUnit({ weights_changed_in_window: true }),
          createUnit({
            stage: 'dataset',
            dataset_id: 'dataset-1',
            verdict: 'insufficient_evidence',
            recommended_vector_weight: null,
            liked_runs: 3,
            disliked_runs: 1,
            required_per_rating: 30,
            analysis: null,
          }),
          createUnit({
            node_id: 'other-node',
            verdict: 'keep_current',
            recommended_vector_weight: null,
          }),
        ],
      }),
    )
    renderTuning()

    await openSection()

    expect(await screen.findByText(key('crossDataset'))).toBeInTheDocument()
    expect(
      screen.getByText(
        `${key('suggested')}:${JSON.stringify({ vector: '0.50', keyword: '0.50' })}`,
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        `${key('evidence')}:${JSON.stringify({
          liked: 40,
          disliked: 35,
          improvement: '+0.20',
          low: '+0.05',
          high: '+0.31',
          affected: 25,
        })}`,
      ),
    ).toBeInTheDocument()
    expect(screen.getByText(key('weightsChanged'))).toBeInTheDocument()
    expect(screen.getByText('Product docs')).toBeInTheDocument()
    expect(
      screen.getByText(
        `${key('insufficient')}:${JSON.stringify({ liked: 3, disliked: 1, required: 30 })}`,
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(key('keep'))).not.toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText(key('advisory'))).toBeInTheDocument()
  })

  it('explains that tracing is off when there is nothing to show', async () => {
    getReport.mockResolvedValue(createReport({ tracing_enabled: false }))
    renderTuning()

    await openSection()

    expect(await screen.findByText(key('tracingOff'))).toBeInTheDocument()
  })

  it('reports a failed request', async () => {
    getReport.mockRejectedValue(new Error('network'))
    renderTuning()

    await openSection()

    expect(await screen.findByRole('alert')).toHaveTextContent(key('error'))
  })
})
