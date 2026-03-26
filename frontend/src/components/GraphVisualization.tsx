import { useEffect, useRef, useState, useCallback } from 'react';
import * as d3 from 'd3';
import { Maximize2 } from 'lucide-react';
import { cn } from '@/utils/cn';
import { useEntityNeighbors, type EntityResponse, type RelationshipResponse } from '@/api/graph';

interface GraphNode extends d3.SimulationNodeDatum {
  id: string;
  name: string;
  type: string;
  document_count: number;
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  id: string;
  relationship_type: string;
  source: string | GraphNode;
  target: string | GraphNode;
}

interface GraphVisualizationProps {
  initialNodes: EntityResponse[];
  initialEdges: RelationshipResponse[];
  onNodeSelect?: (entity: EntityResponse | null) => void;
  onEdgeSelect?: (edge: RelationshipResponse | null) => void;
  className?: string;
}

const TYPE_COLORS: Record<string, string> = {
  person: '#22c55e',
  organization: '#3b82f6',
  product: '#14b8a6',
  technology: '#f59e0b',
  location: '#a855f7',
  event: '#ef4444',
};

function getNodeColor(type: string): string {
  return TYPE_COLORS[type.toLowerCase()] ?? '#71717a';
}

function getNodeRadius(docCount: number): number {
  return Math.max(6, Math.min(24, 6 + Math.sqrt(docCount) * 3));
}

export function GraphVisualization({
  initialNodes,
  initialEdges,
  onNodeSelect,
  onEdgeSelect,
  className,
}: GraphVisualizationProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const simulationRef = useRef<d3.Simulation<GraphNode, GraphLink> | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [links, setLinks] = useState<GraphLink[]>([]);

  const neighborsQuery = useEntityNeighbors(selectedNodeId ?? '', 1);

  // Convert initial data to graph format
  useEffect(() => {
    const graphNodes: GraphNode[] = initialNodes.map((n) => ({
      id: n.id,
      name: n.name,
      type: n.type,
      document_count: n.document_count,
    }));
    const graphLinks: GraphLink[] = initialEdges
      .filter(
        (e) =>
          graphNodes.some((n) => n.id === e.source_id) &&
          graphNodes.some((n) => n.id === e.target_id),
      )
      .map((e) => ({
        id: e.id,
        source: e.source_id,
        target: e.target_id,
        relationship_type: e.relationship_type,
      }));

    setNodes(graphNodes);
    setLinks(graphLinks);
  }, [initialNodes, initialEdges]);

  // Expand neighbors when a node is selected
  useEffect(() => {
    if (!neighborsQuery.data || !selectedNodeId) return;

    const neighborData = neighborsQuery.data.data;
    setNodes((prev) => {
      const existing = new Set(prev.map((n) => n.id));
      const newNodes = neighborData
        .filter((nd) => !existing.has(nd.entity.id))
        .map((nd) => ({
          id: nd.entity.id,
          name: nd.entity.name,
          type: nd.entity.type,
          document_count: nd.entity.document_count,
        }));
      return [...prev, ...newNodes];
    });

    setLinks((prev) => {
      const existing = new Set(prev.map((l) => l.id));
      const newLinks = neighborData
        .filter((nd) => !existing.has(nd.relationship.id))
        .map((nd) => ({
          id: nd.relationship.id,
          source: nd.relationship.source_id,
          target: nd.relationship.target_id,
          relationship_type: nd.relationship.relationship_type,
        }));
      return [...prev, ...newLinks];
    });
  }, [neighborsQuery.data, selectedNodeId]);

  // D3 rendering
  useEffect(() => {
    if (!svgRef.current || !containerRef.current) return;

    const svg = d3.select(svgRef.current);
    const width = containerRef.current.clientWidth;
    const height = containerRef.current.clientHeight;

    svg.selectAll('*').remove();
    svg.attr('viewBox', `0 0 ${width} ${height}`);

    const g = svg.append('g');

    // Zoom
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 5])
      .on('zoom', (event: d3.D3ZoomEvent<SVGSVGElement, unknown>) => {
        g.attr('transform', event.transform.toString());
      });
    svg.call(zoom);

    // Simulation
    const simulation = d3
      .forceSimulation<GraphNode>(nodes)
      .force(
        'link',
        d3
          .forceLink<GraphNode, GraphLink>(links)
          .id((d) => d.id)
          .distance(100),
      )
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide<GraphNode>().radius((d) => getNodeRadius(d.document_count) + 4));

    simulationRef.current = simulation;

    // Links
    const link = g
      .append('g')
      .selectAll<SVGLineElement, GraphLink>('line')
      .data(links)
      .join('line')
      .attr('stroke', '#3f3f46')
      .attr('stroke-width', 1.5)
      .attr('stroke-opacity', 0.6)
      .on('mouseenter', function (_event, d) {
        d3.select(this).attr('stroke', '#14b8a6').attr('stroke-width', 2.5);
        setHoveredEdge(d.id);
      })
      .on('mouseleave', function () {
        d3.select(this).attr('stroke', '#3f3f46').attr('stroke-width', 1.5);
        setHoveredEdge(null);
      })
      .on('click', (_event, d) => {
        const edgeData = initialEdges.find((e) => e.id === d.id);
        if (edgeData) onEdgeSelect?.(edgeData);
      });

    // Edge labels
    const linkLabel = g
      .append('g')
      .selectAll<SVGTextElement, GraphLink>('text')
      .data(links)
      .join('text')
      .attr('text-anchor', 'middle')
      .attr('fill', '#71717a')
      .attr('font-size', '8px')
      .attr('pointer-events', 'none')
      .attr('opacity', 0)
      .text((d) => d.relationship_type);

    // Nodes
    const node = g
      .append('g')
      .selectAll<SVGCircleElement, GraphNode>('circle')
      .data(nodes)
      .join('circle')
      .attr('r', (d) => getNodeRadius(d.document_count))
      .attr('fill', (d) => getNodeColor(d.type))
      .attr('fill-opacity', 0.8)
      .attr('stroke', '#18181b')
      .attr('stroke-width', 2)
      .attr('cursor', 'pointer')
      .on('mouseenter', function () {
        d3.select(this).attr('fill-opacity', 1).attr('stroke', '#fff').attr('stroke-width', 2.5);
      })
      .on('mouseleave', function (_, d) {
        const isSelected = d.id === selectedNodeId;
        d3.select(this)
          .attr('fill-opacity', isSelected ? 1 : 0.8)
          .attr('stroke', isSelected ? '#14b8a6' : '#18181b')
          .attr('stroke-width', 2);
      })
      .on('click', (_, d) => {
        setSelectedNodeId((prev) => (prev === d.id ? null : d.id));
        const entityData = initialNodes.find((n) => n.id === d.id);
        if (entityData) {
          onNodeSelect?.(entityData);
        } else {
          // Node from expansion
          onNodeSelect?.({
            id: d.id,
            name: d.name,
            type: d.type,
            document_count: d.document_count,
            properties: {},
            created_at: '',
          });
        }
      })
      .call(
        d3
          .drag<SVGCircleElement, GraphNode>()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          }),
      );

    // Node labels
    const label = g
      .append('g')
      .selectAll<SVGTextElement, GraphNode>('text')
      .data(nodes)
      .join('text')
      .attr('text-anchor', 'middle')
      .attr('dy', (d) => getNodeRadius(d.document_count) + 14)
      .attr('fill', '#a1a1aa')
      .attr('font-size', '10px')
      .attr('pointer-events', 'none')
      .text((d) => d.name.length > 20 ? d.name.slice(0, 18) + '...' : d.name);

    simulation.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as GraphNode).x ?? 0)
        .attr('y1', (d) => (d.source as GraphNode).y ?? 0)
        .attr('x2', (d) => (d.target as GraphNode).x ?? 0)
        .attr('y2', (d) => (d.target as GraphNode).y ?? 0);

      linkLabel
        .attr('x', (d) => (((d.source as GraphNode).x ?? 0) + ((d.target as GraphNode).x ?? 0)) / 2)
        .attr('y', (d) => (((d.source as GraphNode).y ?? 0) + ((d.target as GraphNode).y ?? 0)) / 2);

      node.attr('cx', (d) => d.x ?? 0).attr('cy', (d) => d.y ?? 0);

      label.attr('x', (d) => d.x ?? 0).attr('y', (d) => d.y ?? 0);
    });

    // Show edge label on hover
    link.on('mouseenter.label', function (_, d) {
      linkLabel.filter((ld) => ld.id === d.id).attr('opacity', 1);
    });
    link.on('mouseleave.label', function () {
      linkLabel.attr('opacity', 0);
    });

    return () => {
      simulation.stop();
    };
  }, [nodes, links, selectedNodeId, initialNodes, initialEdges, onNodeSelect, onEdgeSelect]);

  const fitToView = useCallback(() => {
    if (!svgRef.current || !containerRef.current) return;
    const svg = d3.select(svgRef.current);
    const width = containerRef.current.clientWidth;
    const height = containerRef.current.clientHeight;

    const zoomBehavior = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.2, 5]);
    const transform = d3.zoomIdentity
      .translate(width / 2, height / 2)
      .scale(0.8)
      .translate(-width / 2, -height / 2);

    svg.transition().duration(500).call(zoomBehavior.transform, transform);
  }, []);

  return (
    <div ref={containerRef} className={cn('relative h-full w-full', className)}>
      <svg ref={svgRef} className="h-full w-full" />

      {/* Legend */}
      <div className="absolute bottom-3 left-3 rounded-lg border border-surface-700 bg-surface-900/90 p-2.5 backdrop-blur-sm">
        <div className="grid grid-cols-3 gap-x-4 gap-y-1">
          {Object.entries(TYPE_COLORS).map(([type, color]) => (
            <div key={type} className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
              <span className="text-[10px] capitalize text-surface-400">{type}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Fit to view button */}
      <button
        type="button"
        onClick={fitToView}
        className="absolute right-3 top-3 rounded-lg border border-surface-700 bg-surface-900/90 p-2 text-surface-400 backdrop-blur-sm transition-colors hover:bg-surface-800 hover:text-zinc-100"
        title="Fit to view"
      >
        <Maximize2 className="h-4 w-4" />
      </button>

      {/* Hovered edge label */}
      {hoveredEdge && (
        <div className="absolute left-1/2 top-3 -translate-x-1/2 rounded-md bg-surface-800/90 px-3 py-1.5 text-xs text-surface-300 backdrop-blur-sm">
          {links.find((l) => l.id === hoveredEdge)?.relationship_type}
        </div>
      )}
    </div>
  );
}
