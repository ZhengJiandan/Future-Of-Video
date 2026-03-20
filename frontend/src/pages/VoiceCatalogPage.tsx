import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  CustomerServiceOutlined,
  ReloadOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { DoubaoVoiceCatalogItem, scriptPipelineApi } from '../services/api'

const { Title, Paragraph, Text } = Typography
const { Search } = Input

const styleExplanationMap: Record<string, string> = {
  Vivid: '发声更灵动，起伏更明显，适合外向、年轻、动作感强的角色。',
  Soft: '声音更柔和贴近，适合温柔、陪伴感、亲密表达类角色。',
  Deep: '低频更稳，压场感更强，适合成熟、克制、权威型角色。',
  Clear: '咬字清楚、均衡中性，适合作为通用主力声线。',
  Warm: '整体更温暖友好，适合可靠、治愈、长辈感角色。',
  Cute: '轻巧偏萌，适合少女、宠物拟人、活泼角色。',
  Fun: '口音或角色化特征更明显，适合喜剧、地方特色、记忆点角色。',
}

const scenarioExplanationMap: Record<string, string> = {
  Dubbing: '更适合镜头对白、情绪推进和叙事演绎。',
  General: '通用型音色，适合大多数角色设定和日常对白。',
  Role: '角色感更强，适合需要鲜明人设区分的角色。',
  Fun: '个性化更强，适合喜剧、方言感或标志性角色。',
  'Audio Book': '更适合长句、讲述、旁白和小说朗读。',
}

const buildVoiceHighlights = (voice: DoubaoVoiceCatalogItem): string[] => {
  const highlights: string[] = []
  if (voice.style && styleExplanationMap[voice.style]) {
    highlights.push(styleExplanationMap[voice.style])
  }
  if (voice.scenario && scenarioExplanationMap[voice.scenario]) {
    highlights.push(scenarioExplanationMap[voice.scenario])
  }
  if (voice.language.includes('Accent')) {
    highlights.push('带口音或地域风格，更容易建立角色记忆点，但不适合作为所有角色的默认声线。')
  } else if (voice.language.includes('Chinese')) {
    highlights.push('中文表达稳定，适合主链路里的中文对白场景。')
  } else if (voice.language.includes('English')) {
    highlights.push('适合英文对白、双语角色或外语场景。')
  } else if (voice.language.includes('Japanese') || voice.language.includes('Spanish')) {
    highlights.push('适合跨语种角色或海外语境的片段。')
  }
  return highlights.slice(0, 3)
}

const buildSuggestedUse = (voice: DoubaoVoiceCatalogItem): string => {
  const parts = [voice.gender, voice.style, voice.scenario].filter(Boolean)
  if (!parts.length) {
    return '适合先做试听，再决定是否绑定到正式角色。'
  }
  return `推荐优先用于：${parts.join(' / ')} 类型的角色。`
}

export const VoiceCatalogPage: React.FC = () => {
  const navigate = useNavigate()
  const [voices, setVoices] = useState<DoubaoVoiceCatalogItem[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [scenarioFilter, setScenarioFilter] = useState('all')
  const [languageFilter, setLanguageFilter] = useState('all')
  const [genderFilter, setGenderFilter] = useState('all')

  const loadCatalog = async () => {
    setLoading(true)
    try {
      const response = await scriptPipelineApi.listDoubaoTtsVoices()
      setVoices(response.data.items || [])
    } catch {
      message.error('豆包音色目录加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadCatalog()
  }, [])

  const scenarioOptions = useMemo(
    () =>
      Array.from(new Set(voices.map((item) => item.scenario).filter(Boolean))).map((item) => ({
        label: item,
        value: item,
      })),
    [voices],
  )

  const languageOptions = useMemo(
    () =>
      Array.from(new Set(voices.map((item) => item.language).filter(Boolean))).map((item) => ({
        label: item,
        value: item,
      })),
    [voices],
  )

  const genderOptions = useMemo(
    () =>
      Array.from(new Set(voices.map((item) => item.gender).filter(Boolean))).map((item) => ({
        label: item,
        value: item,
      })),
    [voices],
  )

  const filteredVoices = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase()
    return voices.filter((item) => {
      if (scenarioFilter !== 'all' && item.scenario !== scenarioFilter) {
        return false
      }
      if (languageFilter !== 'all' && item.language !== languageFilter) {
        return false
      }
      if (genderFilter !== 'all' && item.gender !== genderFilter) {
        return false
      }
      if (!normalizedKeyword) {
        return true
      }
      const haystack = [
        item.voice_type,
        item.voice_name,
        item.scenario,
        item.language,
        item.gender,
        item.style,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return haystack.includes(normalizedKeyword)
    })
  }, [genderFilter, keyword, languageFilter, scenarioFilter, voices])

  const groupedVoices = useMemo(() => {
    const groups = new Map<string, DoubaoVoiceCatalogItem[]>()
    filteredVoices.forEach((item) => {
      const key = item.scenario || '未分组'
      const current = groups.get(key) || []
      current.push(item)
      groups.set(key, current)
    })
    return Array.from(groups.entries())
  }, [filteredVoices])

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      <Card
        styles={{
          body: {
            background:
              'linear-gradient(135deg, rgba(16,23,34,0.98) 0%, rgba(18,56,84,0.92) 52%, rgba(227,164,70,0.22) 100%)',
            borderRadius: 20,
          },
        }}
      >
        <Row justify="space-between" align="middle" gutter={[16, 16]}>
          <Col xs={24} lg={16}>
            <Space direction="vertical" size={6}>
              <Tag color="cyan" style={{ width: 'fit-content', margin: 0 }}>
                Voice Atlas
              </Tag>
              <Title level={2} style={{ margin: 0, color: '#fff' }}>
                豆包音色目录
              </Title>
              <Paragraph style={{ margin: 0, color: 'rgba(255,255,255,0.76)' }}>
                这里集中介绍当前接入的豆包 TTS 预置音色。角色档案页会直接复用这份目录做选择，
                先在这里看特点，再回角色档案绑定，会更稳。
              </Paragraph>
            </Space>
          </Col>
          <Col>
            <Space wrap>
              <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void loadCatalog()}>
                刷新目录
              </Button>
              <Button icon={<TeamOutlined />} type="primary" onClick={() => navigate('/characters')}>
                去绑定角色声线
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <Card style={{ borderRadius: 20 }}>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="使用建议"
            description="真正稳定的字段是 `voice_type`。页面里的中文介绍和风格建议用于快速筛选，但最终仍建议先做单句试听，再绑定到正式角色。"
          />
          <Row gutter={[12, 12]}>
            <Col xs={24} lg={10}>
              <Search
                allowClear
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="搜索音色 ID、音色名、语言、风格"
              />
            </Col>
            <Col xs={24} md={8} lg={4}>
              <Select
                style={{ width: '100%' }}
                value={scenarioFilter}
                onChange={setScenarioFilter}
                options={[{ label: '全部场景', value: 'all' }, ...scenarioOptions]}
              />
            </Col>
            <Col xs={24} md={8} lg={5}>
              <Select
                style={{ width: '100%' }}
                value={languageFilter}
                onChange={setLanguageFilter}
                options={[{ label: '全部语言', value: 'all' }, ...languageOptions]}
              />
            </Col>
            <Col xs={24} md={8} lg={5}>
              <Select
                style={{ width: '100%' }}
                value={genderFilter}
                onChange={setGenderFilter}
                options={[{ label: '全部性别', value: 'all' }, ...genderOptions]}
              />
            </Col>
          </Row>
          <Text type="secondary">
            当前共 {voices.length} 个音色，筛选后展示 {filteredVoices.length} 个。
          </Text>
        </Space>
      </Card>

      {groupedVoices.length ? (
        <Space direction="vertical" size={20} style={{ width: '100%' }}>
          {groupedVoices.map(([scenario, items]) => (
            <Card
              key={scenario}
              title={
                <Space>
                  <CustomerServiceOutlined />
                  <span>{scenario}</span>
                  <Tag color="processing">{items.length} 个音色</Tag>
                </Space>
              }
              style={{ borderRadius: 20 }}
            >
              <Row gutter={[20, 20]}>
                {items.map((voice) => (
                  <Col xs={24} md={12} xl={8} key={voice.voice_type}>
                    <Card
                      size="small"
                      style={{ height: '100%', borderRadius: 16, background: '#fbfdff' }}
                      title={
                        <Space wrap>
                          <Text strong>{voice.voice_name}</Text>
                          {voice.gender ? <Tag color="blue">{voice.gender}</Tag> : null}
                          {voice.style ? <Tag color="purple">{voice.style}</Tag> : null}
                        </Space>
                      }
                    >
                      <Space direction="vertical" size={10} style={{ width: '100%' }}>
                        <Text code>{voice.voice_type}</Text>
                        <Space wrap>
                          {voice.language ? <Tag>{voice.language}</Tag> : null}
                          {voice.scenario ? <Tag color="gold">{voice.scenario}</Tag> : null}
                        </Space>
                        <Paragraph style={{ marginBottom: 0 }}>
                          {buildSuggestedUse(voice)}
                        </Paragraph>
                        <Space direction="vertical" size={4} style={{ width: '100%' }}>
                          {buildVoiceHighlights(voice).map((item) => (
                            <Text key={`${voice.voice_type}-${item}`} type="secondary">
                              {item}
                            </Text>
                          ))}
                        </Space>
                        {voice.metadata_warning ? (
                          <Alert
                            type="warning"
                            showIcon
                            message="元数据提示"
                            description={voice.metadata_warning}
                          />
                        ) : null}
                        <Button type="link" style={{ padding: 0 }} onClick={() => navigate(`/characters?voiceType=${voice.voice_type}`)}>
                          用这个音色去创建角色
                        </Button>
                      </Space>
                    </Card>
                  </Col>
                ))}
              </Row>
            </Card>
          ))}
        </Space>
      ) : (
        <Card style={{ borderRadius: 20 }}>
          <Empty description="当前筛选条件下没有音色" />
        </Card>
      )}
    </Space>
  )
}
