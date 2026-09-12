import { createContext, useContext } from "react";
import { api, type ProjectApi } from "../api";

// Each mounted project owns a fixed client. Late uploads cannot target a project
// that the user switched to while FileReader or a render was still in flight.
export const ProjectApiContext = createContext<ProjectApi>(api);
export function useProjectApi(): ProjectApi { return useContext(ProjectApiContext); }
