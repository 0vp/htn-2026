import { evidenceUrl, type RoomObject } from '../rooms/api';

export function ObjectPanel({ roomId, objects, selected, onSelect }: {
  roomId: string;
  objects: RoomObject[];
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const object = objects.find((item) => item.object_id === selected);
  return (
    <div className="absolute right-6 top-40 w-64 max-w-[45vw] bg-blue-deep/95 p-3 text-sm sm:right-9">
      <label htmlFor="room-object" className="label block text-blue-soft">Objects · {objects.length}</label>
      <select id="room-object" value={object?.object_id ?? ''}
        onChange={(event) => onSelect(event.target.value || null)}
        className="mt-2 w-full bg-blue p-2 text-white">
        <option value="">{objects.length ? 'Select an object' : 'No confirmed objects yet'}</option>
        {objects.map((item, index) => (
          <option key={item.object_id} value={item.object_id}>{item.label} · {index + 1}</option>
        ))}
      </select>
      {object && <div className="mt-3 space-y-2">
        <p>{object.size_m.map((value) => value.toFixed(2)).join(' × ')} m</p>
        <p className="text-xs text-blue-soft">Observed surface bounds · facing unknown</p>
        <p className="text-xs">Confirmed in {object.confirmed_views ?? 0} views</p>
        {object.evidence_digest && <img key={object.evidence_digest}
          src={evidenceUrl(roomId, object)} alt={`Camera evidence for ${object.label}`}
          className="max-h-36 w-full object-contain" />}
      </div>}
    </div>
  );
}
