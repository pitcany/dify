import type { RetrievalWeightUnitResponse } from '@dify/contracts/api/console/apps/types.gen'
import { useQuery } from '@tanstack/react-query'
import { useAtomValue } from 'jotai'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { editorAppIdAtom } from '@/app/components/workflow/editor-resource/state'
import { FieldCollapse } from '@/app/components/workflow/nodes/_base/components/collapse'
import { consoleQuery } from '@/service/console'

const i18nPrefix = 'nodes.knowledgeRetrieval.retrievalTuning'

type DatasetName = {
  id: string
  name: string
}

const formatWeight = (weight: number) => weight.toFixed(2)
const formatSigned = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(2)}`

type UnitReportProps = {
  unit: RetrievalWeightUnitResponse
  datasets: DatasetName[]
}

const UnitReport = ({ unit, datasets }: UnitReportProps) => {
  const { t } = useTranslation(['workflow'])
  const title =
    unit.stage === 'cross_dataset'
      ? t(($) => $[`${i18nPrefix}.crossDataset`], { ns: 'workflow' })
      : (datasets.find((dataset) => dataset.id === unit.dataset_id)?.name ?? unit.dataset_id ?? '')
  const { analysis } = unit

  return (
    <div className="space-y-1">
      <div className="system-sm-medium text-text-secondary">{title}</div>
      <div className="system-xs-regular text-text-tertiary">
        {t(($) => $[`${i18nPrefix}.current`], {
          ns: 'workflow',
          vector: formatWeight(unit.current_vector_weight),
          keyword: formatWeight(1 - unit.current_vector_weight),
        })}
      </div>
      {unit.verdict === 'insufficient_evidence' && (
        <div className="system-xs-regular text-text-secondary">
          {t(($) => $[`${i18nPrefix}.insufficient`], {
            ns: 'workflow',
            liked: unit.liked_runs,
            disliked: unit.disliked_runs,
            required: unit.required_per_rating ?? 0,
          })}
        </div>
      )}
      {unit.verdict === 'keep_current' && (
        <div className="system-xs-medium text-text-secondary">
          {t(($) => $[`${i18nPrefix}.keep`], { ns: 'workflow' })}
        </div>
      )}
      {unit.verdict === 'recommend_change' && unit.recommended_vector_weight !== null && (
        <div className="system-xs-medium text-text-accent">
          {t(($) => $[`${i18nPrefix}.suggested`], {
            ns: 'workflow',
            vector: formatWeight(unit.recommended_vector_weight),
            keyword: formatWeight(1 - unit.recommended_vector_weight),
          })}
        </div>
      )}
      {analysis && (
        <div className="system-xs-regular text-text-tertiary">
          {t(($) => $[`${i18nPrefix}.evidence`], {
            ns: 'workflow',
            liked: unit.liked_runs,
            disliked: unit.disliked_runs,
            improvement: formatSigned(analysis.improvement),
            low: formatSigned(analysis.interval_low),
            high: formatSigned(analysis.interval_high),
            affected: Math.round(analysis.affected_share * 100),
          })}
        </div>
      )}
      {unit.weights_changed_in_window && (
        <div className="system-xs-regular text-text-warning">
          {t(($) => $[`${i18nPrefix}.weightsChanged`], { ns: 'workflow' })}
        </div>
      )}
    </div>
  )
}

type RetrievalTuningReportProps = {
  appId: string
  nodeId: string
  datasets: DatasetName[]
}

const RetrievalTuningReport = ({ appId, nodeId, datasets }: RetrievalTuningReportProps) => {
  const { t } = useTranslation(['workflow'])
  const { data, isPending, isError } = useQuery(
    consoleQuery.apps.byAppId.retrievalWeightRecommendations.get.queryOptions({
      input: { params: { app_id: appId } },
    }),
  )

  if (isPending) {
    return (
      <p role="status" className="system-xs-regular text-text-tertiary">
        {t(($) => $[`${i18nPrefix}.loading`], { ns: 'workflow' })}
      </p>
    )
  }
  if (isError) {
    return (
      <p role="alert" className="system-xs-regular text-text-destructive">
        {t(($) => $[`${i18nPrefix}.error`], { ns: 'workflow' })}
      </p>
    )
  }

  const units = data.units.filter((unit) => unit.node_id === nodeId)
  if (!units.length) {
    return (
      <p className="system-xs-regular text-text-tertiary">
        {data.tracing_enabled
          ? t(($) => $[`${i18nPrefix}.empty`], { ns: 'workflow' })
          : t(($) => $[`${i18nPrefix}.tracingOff`], { ns: 'workflow' })}
      </p>
    )
  }

  return (
    <div className="space-y-2">
      <ul className="space-y-2">
        {units.map((unit) => (
          <li
            key={`${unit.stage}:${unit.dataset_id ?? ''}`}
            className="rounded-lg bg-components-panel-on-panel-item-bg p-2"
          >
            <UnitReport unit={unit} datasets={datasets} />
          </li>
        ))}
      </ul>
      <p className="system-xs-regular text-text-tertiary">
        {t(($) => $[`${i18nPrefix}.advisory`], { ns: 'workflow' })}
      </p>
    </div>
  )
}

type RetrievalTuningProps = {
  nodeId: string
  datasets: DatasetName[]
}

// Advisory weighted-score tuning report. Only app editors have message feedback, and the
// report is computed on demand, so it is fetched only while the section is open.
const RetrievalTuning = ({ nodeId, datasets }: RetrievalTuningProps) => {
  const { t } = useTranslation(['workflow'])
  const appId = useAtomValue(editorAppIdAtom)
  const [collapsed, setCollapsed] = useState(true)

  if (!appId) return null

  return (
    <FieldCollapse
      title={t(($) => $[`${i18nPrefix}.title`], { ns: 'workflow' })}
      collapsed={collapsed}
      onCollapse={setCollapsed}
    >
      {!collapsed && <RetrievalTuningReport appId={appId} nodeId={nodeId} datasets={datasets} />}
    </FieldCollapse>
  )
}

export default RetrievalTuning
