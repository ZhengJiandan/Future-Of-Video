import React, { useEffect, useState } from 'react'
import { Alert, Button, Card, Empty, Input, Modal, Space, Spin, Tag, Typography, message } from 'antd'
import { DeleteOutlined, FolderOpenOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { CurrentProjectItem, scriptPipelineApi } from '../services/api'
import { useProjectStore } from '../stores/project'

const { Title, Paragraph, Text } = Typography

const formatTime = (value?: string) => {
  if (!value) {
    return '未知'
  }
  return value.replace('T', ' ').slice(0, 16)
}

export const ProjectListPage: React.FC = () => {
  const navigate = useNavigate()
  const setCurrentProjectId = useProjectStore((state) => state.setCurrentProjectId)
  const clearCurrentProjectId = useProjectStore((state) => state.clearCurrentProjectId)
  const [items, setItems] = useState<CurrentProjectItem[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [deleteLoadingId, setDeleteLoadingId] = useState<string | null>(null)
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [newProjectTitle, setNewProjectTitle] = useState('未命名项目')

  const loadProjects = async () => {
    setLoading(true)
    try {
      const response = await scriptPipelineApi.listProjects()
      setItems(response.data.items || [])
    } catch {
      message.error('项目列表加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadProjects()
  }, [])

  const handleCreateProject = async () => {
    setCreating(true)
    try {
      const response = await scriptPipelineApi.createProject({
        project_title: newProjectTitle.trim() || '未命名项目',
        current_step: 0,
        state: {},
        status: 'draft',
      })
      const projectId = response.data.item.id
      setCurrentProjectId(projectId)
      setCreateModalOpen(false)
      setNewProjectTitle('未命名项目')
      message.success('项目已创建')
      navigate('/script-pipeline')
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '项目创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleOpenProject = (projectId: string) => {
    setCurrentProjectId(projectId)
    navigate('/script-pipeline')
  }

  const handleDeleteProject = async (projectId: string) => {
    setDeleteLoadingId(projectId)
    try {
      await scriptPipelineApi.deleteProject(projectId)
      if (useProjectStore.getState().currentProjectId === projectId) {
        clearCurrentProjectId()
      }
      message.success('项目已删除')
      await loadProjects()
    } catch (requestError: unknown) {
      const responseError = requestError as { response?: { data?: { detail?: string } } }
      message.error(responseError.response?.data?.detail || '项目删除失败')
    } finally {
      setDeleteLoadingId(null)
    }
  }

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      <Card
        style={{
          background: 'linear-gradient(135deg, #12233d 0%, #29588d 52%, #d7af58 100%)',
          border: 'none',
        }}
        bodyStyle={{ padding: 28 }}
      >
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Title level={2} style={{ margin: 0, color: '#fff' }}>
            项目列表
          </Title>
          <Paragraph style={{ marginBottom: 0, color: 'rgba(255,255,255,0.82)' }}>
            每个项目都会保留当前流程阶段、已生成剧本、片段、关键帧和渲染任务状态。
          </Paragraph>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)}>
              新建项目
            </Button>
          </div>
        </Space>
      </Card>

      <Alert
        type="info"
        showIcon
        message="项目会自动保存"
        description="打开项目后，在视频生成页的任何有效修改都会自动写回当前项目。刷新页面后会恢复你刚才打开的那个项目。"
      />

      {loading ? (
        <Card>
          <div style={{ padding: '80px 0', textAlign: 'center' }}>
            <Spin size="large" />
          </div>
        </Card>
      ) : items.length ? (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: 16,
          }}
        >
          {items.map((item) => (
            <Card key={item.id} hoverable>
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <Title level={4} style={{ margin: 0 }}>
                    {item.project_title || '未命名项目'}
                  </Title>
                  <Tag
                    color={
                      item.status === 'completed'
                        ? 'success'
                        : item.status === 'in_progress' || item.status === 'dispatching'
                          ? 'processing'
                          : item.status === 'failed'
                            ? 'error'
                            : item.status === 'cancelled'
                              ? 'orange'
                              : 'default'
                    }
                  >
                    {item.status || 'draft'}
                  </Tag>
                </div>
                <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  {item.summary || '暂无项目摘要'}
                </Paragraph>
                <Space wrap>
                  <Tag>步骤 {item.current_step + 1}</Tag>
                  <Tag>更新于 {formatTime(item.updated_at)}</Tag>
                </Space>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <Button type="primary" icon={<FolderOpenOutlined />} onClick={() => handleOpenProject(item.id)}>
                    打开项目
                  </Button>
                  <Button
                    danger
                    icon={<DeleteOutlined />}
                    loading={deleteLoadingId === item.id}
                    onClick={() => handleDeleteProject(item.id)}
                  >
                    删除
                  </Button>
                </div>
                <Text type="secondary">{item.id}</Text>
              </Space>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <Empty description="还没有历史项目">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)}>
              新建第一个项目
            </Button>
          </Empty>
        </Card>
      )}

      <Modal
        title="新建项目"
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        onOk={handleCreateProject}
        okText="创建并进入"
        confirmLoading={creating}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Text>项目名称</Text>
          <Input value={newProjectTitle} onChange={(event) => setNewProjectTitle(event.target.value)} maxLength={255} />
        </Space>
      </Modal>
    </Space>
  )
}
