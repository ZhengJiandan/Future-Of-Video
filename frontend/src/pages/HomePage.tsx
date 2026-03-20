import React from 'react'
import { Button, Card, Col, Row, Space, Typography } from 'antd'
import {
  AudioOutlined,
  FolderOpenOutlined,
  TeamOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

const { Title, Paragraph } = Typography

export const HomePage: React.FC = () => {
  const navigate = useNavigate()

  return (
    <div>
      <div style={{ textAlign: 'center', marginBottom: 48 }}>
        <Title level={2}>视频创作中心</Title>
        <Paragraph type="secondary" style={{ fontSize: 16, maxWidth: 600, margin: '0 auto' }}>
          从创意描述到最终成片，在同一个项目里完成剧本生成、分段确认、关键帧制作、
          视频渲染和统一音频合成。
        </Paragraph>
        <Space size="large" style={{ marginTop: 24 }}>
          <Button
            type="primary"
            size="large"
            icon={<FolderOpenOutlined />}
            onClick={() => navigate('/projects')}
          >
            打开项目列表
          </Button>
          <Button
            size="large"
            icon={<ThunderboltOutlined />}
            onClick={() => navigate('/script-pipeline')}
          >
            继续当前项目
          </Button>
          <Button
            size="large"
            icon={<TeamOutlined />}
            onClick={() => navigate('/characters/library')}
          >
            角色档案库
          </Button>
          <Button
            size="large"
            icon={<AudioOutlined />}
            onClick={() => navigate('/voices')}
          >
            音色目录
          </Button>
        </Space>
      </div>

      <Row gutter={24} style={{ marginBottom: 48 }}>
        <Col xs={24} sm={8}>
          <Card>
            <Space direction="vertical" size={8}>
              <Title level={4} style={{ margin: 0 }}>
                剧本与分镜
              </Title>
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                根据创意描述生成完整剧本，拆分片段并整理镜头重点。
              </Paragraph>
            </Space>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Space direction="vertical" size={8}>
              <Title level={4} style={{ margin: 0 }}>
                角色与场景
              </Title>
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                在角色档案和场景资料中沉淀稳定设定，便于整条视频保持一致。
              </Paragraph>
            </Space>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Space direction="vertical" size={8}>
              <Title level={4} style={{ margin: 0 }}>
                声音与成片
              </Title>
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                视频完成后统一补充对白、音效和配乐，输出可直接查看和下载的成片。
              </Paragraph>
            </Space>
          </Card>
        </Col>
      </Row>

      <Card title="开始方式">
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          新建项目后可以从头完成整条创作流程；如果已经有项目，直接进入项目列表继续编辑即可。
        </Paragraph>
      </Card>
    </div>
  )
}
