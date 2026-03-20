import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
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
  DeleteOutlined,
  EditOutlined,
  EnvironmentOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { SceneProfile, resolveAssetUrl, scriptPipelineApi } from '../services/api'

const { Title, Paragraph, Text } = Typography
const { Search } = Input

export const SceneLibraryListPage: React.FC = () => {
  const navigate = useNavigate()
  const [scenes, setScenes] = useState<SceneProfile[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [categoryFilter, setCategoryFilter] = useState<string>('all')

  const loadScenes = async () => {
    setLoading(true)
    try {
      const response = await scriptPipelineApi.listScenes()
      setScenes(response.data.items || [])
    } catch {
      message.error('场景档案加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadScenes()
  }, [])

  const handleDelete = async (sceneId: string) => {
    try {
      await scriptPipelineApi.deleteScene(sceneId)
      setScenes((previous) => previous.filter((item) => item.id !== sceneId))
      message.success('场景档案已删除')
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '场景档案删除失败')
    }
  }

  const categoryOptions = useMemo(
    () =>
      Array.from(new Set(scenes.map((item) => item.category).filter(Boolean))).map((item) => ({
        label: item,
        value: item,
      })),
    [scenes],
  )

  const filteredScenes = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase()

    return scenes.filter((item) => {
      const categoryMatched = categoryFilter === 'all' || item.category === categoryFilter
      if (!categoryMatched) {
        return false
      }

      if (!normalizedKeyword) {
        return true
      }

      const haystack = [
        item.name,
        item.category,
        item.scene_type,
        item.location,
        item.description,
        item.atmosphere,
        item.story_function,
        ...(item.tags || []),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()

      return haystack.includes(normalizedKeyword)
    })
  }, [categoryFilter, keyword, scenes])

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      <Card
        styles={{
          body: {
            background:
              'linear-gradient(135deg, rgba(14,20,28,0.96) 0%, rgba(29,67,65,0.92) 56%, rgba(117,164,112,0.24) 100%)',
            borderRadius: 20,
          },
        }}
      >
        <Row justify="space-between" align="middle" gutter={[16, 16]}>
          <Col xs={24} lg={16}>
            <Space direction="vertical" size={6}>
              <Tag color="green" style={{ width: 'fit-content', margin: 0 }}>
                Scene Library
              </Tag>
              <Title level={2} style={{ margin: 0, color: '#fff' }}>
                已保存场景库
              </Title>
              <Paragraph style={{ margin: 0, color: 'rgba(255,255,255,0.74)' }}>
                这里集中管理已入库场景，用于剧本、图片和视频阶段的稳定地点约束。创建与编辑工作单独放在场景工作台。
              </Paragraph>
            </Space>
          </Col>
          <Col>
            <Space wrap>
              <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void loadScenes()}>
                刷新列表
              </Button>
              <Button icon={<PlusOutlined />} type="primary" onClick={() => navigate('/scenes/new')}>
                新建场景
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
            message="使用方式"
            description="先在场景工作台维护地点、时间、天气、氛围和参考图，保存后再回到这里筛选、查看和删除。"
          />

          <Row gutter={[12, 12]}>
            <Col xs={24} md={14}>
              <Search
                allowClear
                placeholder="搜索场景名称、分类、类型、地点、剧情功能或标签"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
              />
            </Col>
            <Col xs={24} md={10}>
              <Select
                style={{ width: '100%' }}
                value={categoryFilter}
                onChange={setCategoryFilter}
                options={[{ label: '全部分类', value: 'all' }, ...categoryOptions]}
              />
            </Col>
          </Row>

          <Text type="secondary">
            共 {scenes.length} 个场景，当前显示 {filteredScenes.length} 个
          </Text>
        </Space>
      </Card>

      {filteredScenes.length ? (
        <Row gutter={[20, 20]}>
          {filteredScenes.map((scene) => (
            <Col xs={24} md={12} xl={8} key={scene.id}>
              <Card
                hoverable
                style={{ height: '100%', borderRadius: 20 }}
                cover={
                  scene.reference_image_url ? (
                    <div
                      style={{
                        height: 240,
                        overflow: 'hidden',
                        background:
                          'radial-gradient(circle at top, rgba(44,104,91,0.24), rgba(14,18,27,0.96))',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        padding: 16,
                      }}
                    >
                      <Image
                        src={resolveAssetUrl(scene.reference_image_url)}
                        alt={scene.name}
                        style={{ maxHeight: 208, objectFit: 'contain' }}
                        preview
                      />
                    </div>
                  ) : undefined
                }
                actions={[
                  <Button
                    key="edit"
                    type="link"
                    icon={<EditOutlined />}
                    onClick={() => navigate(`/scenes/edit?sceneId=${scene.id}`)}
                  >
                    编辑
                  </Button>,
                  <Button key="create" type="link" icon={<PlusOutlined />} onClick={() => navigate('/scenes/new')}>
                    继续创建
                  </Button>,
                  <Button
                    key="delete"
                    type="link"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => void handleDelete(scene.id)}
                  >
                    删除
                  </Button>,
                ]}
              >
                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  <Space wrap>
                    <Tag color="green" icon={<EnvironmentOutlined />}>
                      {scene.name}
                    </Tag>
                    {scene.category ? <Tag>{scene.category}</Tag> : null}
                    {scene.scene_type ? <Tag color="processing">{scene.scene_type}</Tag> : null}
                    {scene.location ? <Tag color="cyan">{scene.location}</Tag> : null}
                  </Space>

                  {scene.description ? <Text>{scene.description}</Text> : null}
                  {scene.atmosphere ? <Text type="secondary">氛围: {scene.atmosphere}</Text> : null}
                  {scene.story_function ? <Text type="secondary">剧情功能: {scene.story_function}</Text> : null}
                  {scene.time_setting ? <Text type="secondary">时间: {scene.time_setting}</Text> : null}
                  {scene.weather ? <Text type="secondary">天气: {scene.weather}</Text> : null}
                  {scene.lighting ? <Text type="secondary">灯光: {scene.lighting}</Text> : null}

                  {scene.must_have_elements?.length ? (
                    <Space wrap size={[6, 6]}>
                      {scene.must_have_elements.map((item) => (
                        <Tag key={`${scene.id}-must-${item}`} color="blue">
                          {item}
                        </Tag>
                      ))}
                    </Space>
                  ) : null}

                  {scene.tags?.length ? (
                    <Space wrap size={[6, 6]}>
                      {scene.tags.map((item) => (
                        <Tag key={`${scene.id}-tag-${item}`}>{item}</Tag>
                      ))}
                    </Space>
                  ) : null}
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      ) : (
        <Card style={{ borderRadius: 20 }}>
          <Empty
            description={keyword || categoryFilter !== 'all' ? '没有符合筛选条件的场景' : '还没有已保存场景'}
          >
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => void loadScenes()}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/scenes/new')}>
                去创建场景
              </Button>
            </Space>
          </Empty>
        </Card>
      )}
    </Space>
  )
}
