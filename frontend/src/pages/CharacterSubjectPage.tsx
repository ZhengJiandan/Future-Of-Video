import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Image,
  Input,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  AppstoreOutlined,
  AudioOutlined,
  DeleteOutlined,
  EyeOutlined,
  FolderOpenOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { CharacterAssetNav } from '../components/CharacterAssetNav'
import {
  CharacterProfile,
  KlingCollectionResponse,
  KlingEntityRecord,
  klingApi,
  resolveAssetUrl,
  resolveDisplayAssetUrl,
  scriptPipelineApi,
} from '../services/api'

const { Title, Paragraph, Text } = Typography
const { Search, TextArea } = Input

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const getStringField = (record: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }
    if (typeof value === 'number') {
      return String(value)
    }
  }
  return ''
}

const flattenKlingEntityRecords = (payload: unknown): KlingEntityRecord[] => {
  if (Array.isArray(payload)) {
    const flattened: KlingEntityRecord[] = []
    for (const item of payload) {
      flattened.push(...flattenKlingEntityRecords(item))
    }
    return flattened
  }

  if (!isRecord(payload)) {
    return []
  }

  const taskResult = payload.task_result
  if (isRecord(taskResult)) {
    for (const key of ['voices', 'elements']) {
      const nestedValue = taskResult[key]
      if (Array.isArray(nestedValue)) {
        return flattenKlingEntityRecords(nestedValue)
      }
    }
  }

  const candidates = ['items', 'list', 'records', 'voices', 'elements', 'data']
  for (const key of candidates) {
    const value = payload[key]
    if (Array.isArray(value) || isRecord(value)) {
      const nested = flattenKlingEntityRecords(value)
      if (nested.length) {
        return nested
      }
    }
  }

  const entityId = getStringField(payload, ['element_id', 'voice_id', 'id'])
  const entityName = getStringField(payload, ['name', 'element_name', 'voice_name', 'title', 'label'])
  if (entityId || entityName) {
    return [payload]
  }
  return []
}

const normalizeKlingItems = (payload: KlingCollectionResponse | KlingEntityRecord | unknown): KlingEntityRecord[] => {
  return flattenKlingEntityRecords(payload)
}

const getEntityId = (item: KlingEntityRecord) => getStringField(item, ['element_id', 'voice_id', 'id'])
const getEntityName = (item: KlingEntityRecord) =>
  getStringField(item, ['name', 'element_name', 'voice_name', 'title', 'label'])
const getEntityStatus = (item: KlingEntityRecord) =>
  getStringField(item, ['status', 'task_status', 'state', 'element_status', 'train_status'])
const getEntitySummary = (item: KlingEntityRecord) =>
  getStringField(item, ['description', 'summary', 'remark', 'prompt_text', 'text'])
const getEntityImageUrl = (item: KlingEntityRecord) =>
  getStringField(item, ['cover_url', 'image_url', 'preview_url', 'icon_url', 'avatar_url', 'resource', 'url'])
const getVoiceLanguage = (item: KlingEntityRecord) => getStringField(item, ['language', 'lang', 'locale'])
const getVoiceOwner = (item: KlingEntityRecord) => getStringField(item, ['owned_by', 'owner', 'provider', 'vendor'])

const buildVoiceOptionValue = (source: 'custom' | 'preset', voiceId: string) => `${source}:${voiceId}`

const buildJsonPayload = (rawText: string) => {
  const normalized = rawText.trim()
  if (!normalized) {
    return {}
  }
  const parsed = JSON.parse(normalized) as unknown
  if (!isRecord(parsed)) {
    throw new Error('附加参数必须是 JSON 对象')
  }
  return parsed
}

const collectCharacterSubjectImages = (character: CharacterProfile): string[] => {
  const candidates = [
    character.reference_image_url,
    character.face_closeup_image_url,
    character.three_view_image_url,
    ...(character.identity_reference_images || []).map((item) => item.url),
  ]

  const normalized = new Set<string>()
  for (const item of candidates) {
    const value = String(item || '').trim()
    if (!value) {
      continue
    }
    normalized.add(resolveAssetUrl(value))
    if (normalized.size >= 4) {
      break
    }
  }

  return Array.from(normalized)
}

export const CharacterSubjectPage: React.FC = () => {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [characters, setCharacters] = useState<CharacterProfile[]>([])
  const [subjects, setSubjects] = useState<KlingEntityRecord[]>([])
  const [customVoices, setCustomVoices] = useState<KlingEntityRecord[]>([])
  const [presetVoices, setPresetVoices] = useState<KlingEntityRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [subjectKeyword, setSubjectKeyword] = useState('')
  const [selectedCharacterId, setSelectedCharacterId] = useState('')
  const [selectedVoiceOption, setSelectedVoiceOption] = useState('')
  const [subjectName, setSubjectName] = useState('')
  const [extraJson, setExtraJson] = useState('')
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailRecord, setDetailRecord] = useState<KlingEntityRecord | null>(null)

  const loadData = async () => {
    setLoading(true)
    try {
      const [characterResponse, subjectResponse, customVoiceResponse, presetVoiceResponse] = await Promise.all([
        scriptPipelineApi.listCharacters(),
        klingApi.listSubjects({ page_size: 100 }),
        klingApi.listCustomVoices({ page_size: 100 }),
        klingApi.listPresetVoices({ page_size: 100 }),
      ])
      setCharacters(characterResponse.data.items || [])
      setSubjects(normalizeKlingItems(subjectResponse.data))
      setCustomVoices(normalizeKlingItems(customVoiceResponse.data))
      setPresetVoices(normalizeKlingItems(presetVoiceResponse.data))
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '角色主体页面加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [])

  const voiceOptions = useMemo(
    () => [
      ...customVoices.map((item) => {
        const voiceId = getEntityId(item)
        const voiceName = getEntityName(item) || voiceId || '未命名自定义音色'
        const language = getVoiceLanguage(item)
        const owner = getVoiceOwner(item)
        return {
          label: ['自定义音色', voiceName, language, owner].filter(Boolean).join(' · '),
          value: buildVoiceOptionValue('custom', voiceId),
        }
      }),
      ...presetVoices.map((item) => {
        const voiceId = getEntityId(item)
        const voiceName = getEntityName(item) || voiceId || '未命名官方音色'
        const language = getVoiceLanguage(item)
        const owner = getVoiceOwner(item)
        return {
          label: ['官方音色', voiceName, language, owner].filter(Boolean).join(' · '),
          value: buildVoiceOptionValue('preset', voiceId),
        }
      }),
    ],
    [customVoices, presetVoices],
  )

  useEffect(() => {
    const queryCharacterId = searchParams.get('characterId')?.trim() || ''
    if (queryCharacterId) {
      setSelectedCharacterId(queryCharacterId)
    }
  }, [searchParams])

  useEffect(() => {
    const queryVoiceId = searchParams.get('voiceId')?.trim() || ''
    const queryVoiceType = searchParams.get('voiceType')?.trim() || ''
    if (!queryVoiceId || !queryVoiceType) {
      return
    }
    const nextValue = buildVoiceOptionValue(queryVoiceType === 'preset' ? 'preset' : 'custom', queryVoiceId)
    if (voiceOptions.some((item) => item.value === nextValue)) {
      setSelectedVoiceOption(nextValue)
    }
  }, [searchParams, voiceOptions])

  const selectedCharacter = useMemo(
    () => characters.find((item) => item.id === selectedCharacterId) || null,
    [characters, selectedCharacterId],
  )

  useEffect(() => {
    if (selectedCharacter && !subjectName.trim()) {
      setSubjectName(selectedCharacter.name || '')
    }
  }, [selectedCharacter, subjectName])

  const selectedVoiceLabel = useMemo(
    () => voiceOptions.find((item) => item.value === selectedVoiceOption)?.label || '',
    [selectedVoiceOption, voiceOptions],
  )

  const filteredSubjects = useMemo(() => {
    const keyword = subjectKeyword.trim().toLowerCase()
    if (!keyword) {
      return subjects
    }
    return subjects.filter((item) => {
      const haystack = [
        getEntityId(item),
        getEntityName(item),
        getEntityStatus(item),
        getEntitySummary(item),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return haystack.includes(keyword)
    })
  }, [subjectKeyword, subjects])

  const handleCreateSubject = async () => {
    if (!selectedCharacter) {
      message.warning('请先选择一个角色档案')
      return
    }
    if (!selectedCharacter.reference_image_url) {
      message.warning('当前角色没有参考图，无法生成主体')
      return
    }

    const subjectImages = collectCharacterSubjectImages(selectedCharacter)
    if (subjectImages.length < 2) {
      message.warning('可灵角色主体至少需要 2 张参考图，请先补充三视图或面部特写')
      return
    }

    let extraBody: Record<string, unknown> = {}
    try {
      extraBody = buildJsonPayload(extraJson)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '附加参数解析失败')
      return
    }

    setCreating(true)
    try {
      const response = await klingApi.createSubject({
        name: subjectName.trim() || selectedCharacter.name,
        image: subjectImages[0],
        extra_body: {
          ...extraBody,
          element_description:
            selectedCharacter.llm_summary ||
            selectedCharacter.description ||
            `${selectedCharacter.name}${selectedCharacter.role ? `，${selectedCharacter.role}` : ''}`,
          element_refer_list: subjectImages.slice(1, 4).map((url) => ({ image_url: url })),
        },
      })
      const createdSubject = response.data
      const createdSubjectId = getEntityId(createdSubject)
      const createdSubjectName =
        getEntityName(createdSubject) || subjectName.trim() || selectedCharacter.name
      const createdSubjectStatus = getEntityStatus(createdSubject)

      if (createdSubjectId) {
        try {
          await scriptPipelineApi.bindCharacterSubject(selectedCharacter.id, {
            kling_subject_id: createdSubjectId,
            kling_subject_name: createdSubjectName,
            kling_subject_status: createdSubjectStatus,
          })
        } catch (bindError: unknown) {
          const bindResponseError = bindError as { response?: { data?: { detail?: string } } }
          message.warning(
            bindResponseError.response?.data?.detail || '角色主体已创建，但回写角色档案失败',
          )
        }
      }
      message.success(
        [
          `角色主体已创建${createdSubjectId ? '并绑定到角色档案' : ''}`,
          selectedVoiceLabel ? `当前选择音色为「${selectedVoiceLabel}」` : '',
        ]
          .filter(Boolean)
          .join('，'),
      )
      await loadData()
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '角色主体创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleDeleteSubject = async (subjectId: string) => {
    try {
      await klingApi.deleteSubject(subjectId)
      setSubjects((previous) => previous.filter((item) => getEntityId(item) !== subjectId))
      message.success('角色主体已删除')
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '角色主体删除失败')
    }
  }

  const handleBindSubjectToCharacter = async (item: KlingEntityRecord) => {
    if (!selectedCharacter) {
      message.warning('请先选择一个角色档案')
      return
    }

    const subjectId = getEntityId(item)
    if (!subjectId) {
      message.warning('当前主体缺少可用 ID，无法绑定')
      return
    }

    try {
      await scriptPipelineApi.bindCharacterSubject(selectedCharacter.id, {
        kling_subject_id: subjectId,
        kling_subject_name: getEntityName(item) || selectedCharacter.name,
        kling_subject_status: getEntityStatus(item),
      })
      message.success(`已将主体绑定到角色「${selectedCharacter.name}」`)
      await loadData()
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '角色主体绑定失败')
    }
  }

  const handleOpenDetail = async (subjectId: string, fallbackItem: KlingEntityRecord) => {
    setDetailOpen(true)
    setDetailLoading(true)
    setDetailRecord(fallbackItem)
    try {
      const response = await klingApi.getSubject(subjectId)
      setDetailRecord(response.data)
    } catch {
      setDetailRecord(fallbackItem)
    } finally {
      setDetailLoading(false)
    }
  }

  const handleSelectCharacterFromLibrary = (characterId: string) => {
    setSelectedCharacterId(characterId)
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('characterId', characterId)
    setSearchParams(nextParams)
  }

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      <Card
        styles={{
          body: {
            background:
              'linear-gradient(135deg, rgba(14,20,31,0.98) 0%, rgba(15,58,80,0.92) 54%, rgba(189,133,51,0.18) 100%)',
            borderRadius: 20,
          },
        }}
      >
        <Row justify="space-between" align="middle" gutter={[16, 16]}>
          <Col xs={24} lg={16}>
            <Space direction="vertical" size={6}>
              <Tag color="cyan" style={{ width: 'fit-content', margin: 0 }}>
                Character Subjects
              </Tag>
              <Title level={2} style={{ margin: 0, color: '#fff' }}>
                角色主体工作台
              </Title>
              <Paragraph style={{ margin: 0, color: 'rgba(255,255,255,0.74)' }}>
                这里是角色资产的上游入口。先从角色档案提取可灵主体，再把主体与音色配合起来，供后续视频生成直接调用。
              </Paragraph>
            </Space>
          </Col>
          <Col>
            <Space wrap>
              <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void loadData()}>
                刷新数据
              </Button>
              <Button icon={<FolderOpenOutlined />} onClick={() => navigate('/characters/library')}>
                查看角色档案
              </Button>
              <Button icon={<AudioOutlined />} type="primary" onClick={() => navigate('/characters/voices')}>
                管理角色音色
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <CharacterAssetNav current="subjects" />

      <Alert
        type="info"
        showIcon
        message="当前接入说明"
        description="主体页直接调用可灵主体相关接口。生成主体时可同时选定一个角色音色，方便你在同一套角色资产工作流里完成主体与声音的搭配。"
      />

      <Row gutter={[20, 20]} align="top">
        <Col xs={24} xl={10}>
          <Card title="从角色档案生成主体" style={{ borderRadius: 20 }}>
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <Select
                showSearch
                placeholder="选择角色档案"
                optionFilterProp="label"
                value={selectedCharacterId || undefined}
                onChange={(value) => handleSelectCharacterFromLibrary(value)}
                options={characters.map((item) => ({
                  label: `${item.name}${item.role ? ` · ${item.role}` : ''}`,
                  value: item.id,
                }))}
              />

              <Input
                placeholder="主体名称"
                value={subjectName}
                onChange={(event) => setSubjectName(event.target.value)}
              />

              <Select
                allowClear
                showSearch
                placeholder="选择角色音色"
                optionFilterProp="label"
                value={selectedVoiceOption || undefined}
                onChange={(value) => setSelectedVoiceOption(value)}
                options={voiceOptions}
              />

              <TextArea
                rows={6}
                value={extraJson}
                onChange={(event) => setExtraJson(event.target.value)}
                placeholder={'附加参数 JSON，可选\n例如：{"category":"主角","callback_url":"https://example.com/callback"}'}
              />

              <Space wrap>
                <Button type="primary" loading={creating} icon={<AppstoreOutlined />} onClick={() => void handleCreateSubject()}>
                  生成角色主体
                </Button>
                <Button icon={<AudioOutlined />} onClick={() => navigate('/characters/voices')}>
                  去选音色
                </Button>
              </Space>
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={14}>
          <Card title="当前角色资产摘要" style={{ borderRadius: 20 }}>
            {selectedCharacter ? (
              <Row gutter={[20, 20]} align="middle">
                <Col xs={24} md={10}>
                  {selectedCharacter.reference_image_url ? (
                    <Image
                      src={resolveDisplayAssetUrl(
                        selectedCharacter.reference_image_url,
                        selectedCharacter.reference_image_thumbnail_url,
                      )}
                      alt={selectedCharacter.name}
                      style={{ borderRadius: 16, maxHeight: 260, objectFit: 'contain' }}
                      preview={{ src: resolveAssetUrl(selectedCharacter.reference_image_url) }}
                    />
                  ) : (
                    <Empty
                      description="当前角色还没有参考图"
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                    />
                  )}
                </Col>
                <Col xs={24} md={14}>
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    <Space wrap>
                      <Tag color="processing">{selectedCharacter.name}</Tag>
                      {selectedCharacter.role ? <Tag>{selectedCharacter.role}</Tag> : null}
                      {selectedCharacter.category ? <Tag color="purple">{selectedCharacter.category}</Tag> : null}
                    </Space>
                    {selectedCharacter.llm_summary ? <Text>{selectedCharacter.llm_summary}</Text> : null}
                    <Descriptions column={1} size="small">
                      <Descriptions.Item label="参考图">
                        {selectedCharacter.reference_image_original_name || '已配置'}
                      </Descriptions.Item>
                      <Descriptions.Item label="推荐音色">
                        {selectedVoiceLabel || '暂未选择'}
                      </Descriptions.Item>
                      <Descriptions.Item label="已绑定主体">
                        {selectedCharacter.kling_subject_name ||
                          selectedCharacter.kling_subject_id ||
                          '暂未绑定'}
                      </Descriptions.Item>
                      <Descriptions.Item label="主体名称">
                        {subjectName.trim() || selectedCharacter.name}
                      </Descriptions.Item>
                    </Descriptions>
                    <Button onClick={() => navigate(`/characters/edit?characterId=${selectedCharacter.id}`)}>
                      去完善角色档案
                    </Button>
                  </Space>
                </Col>
              </Row>
            ) : (
              <Empty
                description="先选择一个角色档案"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            )}
          </Card>
        </Col>
      </Row>

      <Card title="角色档案快速选择" style={{ borderRadius: 20 }}>
        {characters.length ? (
          <Row gutter={[16, 16]}>
            {characters.slice(0, 8).map((character) => (
              <Col xs={24} md={12} xl={8} key={character.id}>
                <Card size="small" style={{ borderRadius: 16 }}>
                  <Space direction="vertical" size={10} style={{ width: '100%' }}>
                    <Space wrap>
                      <Tag color="blue">{character.name}</Tag>
                      {character.role ? <Tag>{character.role}</Tag> : null}
                    </Space>
                    <Text type="secondary">{character.llm_summary || character.description || '暂无摘要'}</Text>
                    <Space wrap>
                      <Button type="primary" size="small" onClick={() => handleSelectCharacterFromLibrary(character.id)}>
                        用于生成主体
                      </Button>
                      <Button size="small" onClick={() => navigate(`/characters/edit?characterId=${character.id}`)}>
                        编辑角色
                      </Button>
                    </Space>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        ) : (
          <Empty description="还没有可用的角色档案">
            <Button type="primary" onClick={() => navigate('/characters/new')}>
              去创建角色档案
            </Button>
          </Empty>
        )}
      </Card>

      <Card title="已创建角色主体" style={{ borderRadius: 20 }}>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Search
            allowClear
            value={subjectKeyword}
            onChange={(event) => setSubjectKeyword(event.target.value)}
            placeholder="搜索主体名称、ID、状态或摘要"
          />
          <Text type="secondary">
            共 {subjects.length} 个主体，当前显示 {filteredSubjects.length} 个
          </Text>
          {filteredSubjects.length ? (
            <Row gutter={[16, 16]}>
              {filteredSubjects.map((item) => {
                const subjectId = getEntityId(item)
                const subjectNameText = getEntityName(item) || subjectId || '未命名主体'
                const previewUrl = getEntityImageUrl(item)
                return (
                  <Col xs={24} md={12} xl={8} key={subjectId || subjectNameText}>
                    <Card
                      hoverable
                      style={{ height: '100%', borderRadius: 18 }}
                      cover={
                        previewUrl ? (
                          <div
                            style={{
                              height: 240,
                              padding: 16,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              background:
                                'radial-gradient(circle at top, rgba(38,74,122,0.22), rgba(13,18,28,0.96))',
                            }}
                          >
                            <Image
                              src={resolveAssetUrl(previewUrl)}
                              alt={subjectNameText}
                              style={{ maxHeight: 208, objectFit: 'contain' }}
                            />
                          </div>
                        ) : undefined
                      }
                      actions={[
                        <Button
                          key="bind"
                          type="link"
                          icon={<AppstoreOutlined />}
                          onClick={() => void handleBindSubjectToCharacter(item)}
                        >
                          绑定到当前角色
                        </Button>,
                        <Button
                          key="detail"
                          type="link"
                          icon={<EyeOutlined />}
                          onClick={() => void handleOpenDetail(subjectId, item)}
                        >
                          查看详情
                        </Button>,
                        <Button
                          key="delete"
                          type="link"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={() => void handleDeleteSubject(subjectId)}
                        >
                          删除
                        </Button>,
                      ]}
                    >
                      <Space direction="vertical" size={10} style={{ width: '100%' }}>
                        <Space wrap>
                          <Tag color="processing">{subjectNameText}</Tag>
                          {getEntityStatus(item) ? <Tag color="gold">{getEntityStatus(item)}</Tag> : null}
                        </Space>
                        {subjectId ? <Text type="secondary">ID: {subjectId}</Text> : null}
                        {getEntitySummary(item) ? <Text type="secondary">{getEntitySummary(item)}</Text> : null}
                      </Space>
                    </Card>
                  </Col>
                )
              })}
            </Row>
          ) : (
            <Empty description="还没有角色主体" />
          )}
        </Space>
      </Card>

      <Drawer
        width={560}
        title="角色主体详情"
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {detailLoading ? <Alert type="info" showIcon message="正在加载详情..." /> : null}
          {detailRecord ? (
            <>
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="主体 ID">{getEntityId(detailRecord) || '-'}</Descriptions.Item>
                <Descriptions.Item label="主体名称">{getEntityName(detailRecord) || '-'}</Descriptions.Item>
                <Descriptions.Item label="状态">{getEntityStatus(detailRecord) || '-'}</Descriptions.Item>
                <Descriptions.Item label="摘要">{getEntitySummary(detailRecord) || '-'}</Descriptions.Item>
              </Descriptions>
              <Card size="small" title="原始返回">
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {JSON.stringify(detailRecord, null, 2)}
                </pre>
              </Card>
            </>
          ) : (
            <Empty description="暂无详情" />
          )}
        </Space>
      </Drawer>
    </Space>
  )
}
